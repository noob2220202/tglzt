"""Processes PENDING orders by polling SQLite. No Redis required."""
import asyncio
from decimal import Decimal

import httpx
import structlog

from core.cache import cache_delete
from core.config import settings
from core.db import get_conn, init_db
from core.lzt import LZTClient

logger = structlog.get_logger(__name__)

LZT_BALANCE_CACHE_KEY = "lzt:balance"
POLL_INTERVAL = 2  # seconds between DB polls


async def _send_message(user_id: int, text: str) -> None:
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                json={"chat_id": user_id, "text": text, "parse_mode": "HTML"},
                timeout=10.0,
            )
        except Exception as exc:
            logger.warning("send_message_failed", user_id=user_id, error=str(exc))


async def _send_document(user_id: int, file_bytes: bytes, filename: str, caption: str) -> None:
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{settings.bot_token}/sendDocument",
                data={"chat_id": user_id, "caption": caption, "parse_mode": "HTML"},
                files={"document": (filename, file_bytes, "application/octet-stream")},
                timeout=30.0,
            )
        except Exception as exc:
            logger.warning("send_document_failed", user_id=user_id, error=str(exc))


async def _notify_admins(text: str) -> None:
    async with httpx.AsyncClient() as client:
        for admin_id in settings.admin_tg_ids:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                    json={"chat_id": admin_id, "text": text, "parse_mode": "HTML"},
                    timeout=10.0,
                )
            except Exception as exc:
                logger.warning("admin_notify_failed", admin_id=admin_id, error=str(exc))


async def _claim_order() -> dict | None:
    """Atomically claim next PENDING order → PURCHASING. Returns order dict or None."""
    async with get_conn() as db:
        row = await (
            await db.execute(
                "SELECT id FROM orders WHERE status = 'PENDING' ORDER BY created_at LIMIT 1"
            )
        ).fetchone()
        if row is None:
            return None

        cursor = await db.execute(
            "UPDATE orders SET status = 'PURCHASING' WHERE id = ? AND status = 'PENDING'",
            (row["id"],),
        )
        await db.commit()

        if cursor.rowcount == 0:
            return None  # claimed by another process

        order = await (
            await db.execute("SELECT * FROM orders WHERE id = ?", (row["id"],))
        ).fetchone()
        return dict(order) if order else None


async def process_order(lzt: LZTClient, order: dict) -> None:
    order_id = order["id"]
    user_id = order["user_id"]
    item_id = order["item_id"]
    lzt_price = float(order["lzt_price_usd"])

    logger.info("processing_order", order_id=order_id, user_id=user_id, item_id=item_id)

    try:
        # Check LZT balance
        lzt_balance = await lzt.get_balance()
        if lzt_balance < settings.lzt_balance_min_usd:
            await _notify_admins(
                f"🚨 <b>LZT 잔액 부족</b>\n\n현재 잔액: {lzt_balance:.2f} USD\n즉시 충전이 필요합니다"
            )
            raise RuntimeError(f"LZT 잔액 부족: {lzt_balance:.2f} USD")

        buy_result = await lzt.fast_buy(item_id, lzt_price)
        logger.info("fast_buy_done", order_id=order_id, keys=list(buy_result.keys()))

        if not buy_result or buy_result.get("status") == 0:
            msg = buy_result.get("message", "알 수 없는 오류") if buy_result else "빈 응답"
            raise RuntimeError(f"fast_buy 실패: {msg}")

        item_data = buy_result.get("item", buy_result)

        phone = (
            item_data.get("account_phone_number")
            or item_data.get("phone")
            or item_data.get("login")
            or ""
        )
        twofa = (
            item_data.get("account_password")
            or item_data.get("twofa_password")
            or item_data.get("password")
            or ""
        )

        # Get login code (retry 3x with 5s delay)
        login_code = ""
        for attempt in range(3):
            try:
                code_result = await lzt.request_login_code(item_id)
                login_code = code_result.get("telegram_login_code") or code_result.get("code") or ""
                if login_code:
                    break
            except Exception as exc:
                logger.warning("login_code_attempt", attempt=attempt, error=str(exc))
            if attempt < 2:
                await asyncio.sleep(5)

        # Download session file
        session_url = item_data.get("account_session_file") or item_data.get("session_file_url") or ""
        session_bytes = None
        session_filename = ""
        if session_url:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(session_url, timeout=30.0)
                    if resp.status_code == 200:
                        session_bytes = resp.content
                        session_filename = f"session_{item_id}.session"
            except Exception as exc:
                logger.warning("session_download_failed", error=str(exc))

        # Save to DB
        async with get_conn() as db:
            await db.execute(
                """
                UPDATE orders
                SET status = 'DELIVERED',
                    phone = ?, login_code = ?, twofa_password = ?,
                    session_path = ?, delivered_at = datetime('now')
                WHERE id = ?
                """,
                (phone, login_code, twofa or None, session_filename or None, order_id),
            )
            await db.commit()

        cache_delete(LZT_BALANCE_CACHE_KEY)

        twofa_display = twofa or "없음"
        delivery_text = (
            "✅ <b>구매 완료!</b>\n\n"
            "<blockquote>"
            f"📱 전화번호\n<code>{phone}</code>\n\n"
            f"🔐 로그인 인증번호\n<code>{login_code or '요청중...'}</code>\n\n"
            f"🔑 2FA 비밀번호\n<code>{twofa_display}</code>"
            "</blockquote>\n\n"
            "📖 <b>사용법</b>\n"
            "<i>1. 텔레그램 앱 → 전화번호 입력\n"
            "2. 위 인증번호 입력\n"
            "3. 2FA 비밀번호 있으면 입력\n"
            "4. 즉시 비번/번호 변경 권장</i>\n\n"
            "⚠️ <b>주의</b>\n"
            f"<i>인증번호는 5분간만 유효\n재발급은 /resend {order_id}</i>"
        )
        await _send_message(user_id, delivery_text)

        if session_bytes and session_filename:
            await _send_document(user_id, session_bytes, session_filename, f"📁 세션 파일 - 주문 {order_id[:8]}")

        logger.info("order_delivered", order_id=order_id)

    except Exception as exc:
        logger.error("order_failed", order_id=order_id, error=str(exc), exc_info=True)

        async with get_conn() as db:
            order_row = await (
                await db.execute("SELECT price_paid FROM orders WHERE id = ?", (order_id,))
            ).fetchone()

            if order_row:
                await db.execute(
                    """
                    UPDATE orders SET status = 'FAILED', fail_reason = ? WHERE id = ?
                    """,
                    (str(exc)[:500], order_id),
                )
                await db.execute(
                    "UPDATE users SET balance_usdt = CAST(CAST(balance_usdt AS REAL) + ? AS TEXT) WHERE tg_id = ?",
                    (float(Decimal(order_row["price_paid"])), user_id),
                )
                await db.commit()

            bal_row = await (
                await db.execute("SELECT balance_usdt FROM users WHERE tg_id = ?", (user_id,))
            ).fetchone()

        new_balance = Decimal(bal_row["balance_usdt"]) if bal_row else Decimal("0")
        await _send_message(
            user_id,
            "❌ <b>구매에 실패했습니다</b>\n\n"
            "<blockquote>"
            f"사유: {str(exc)[:200]}\n"
            f"주문번호: <code>{order_id}</code>\n\n"
            "💰 잔액이 자동 환불되었습니다\n"
            f"현재 잔액: <b>{new_balance:.4f} USDT</b>"
            "</blockquote>\n\n"
            "<i>다른 매물을 선택해주세요</i>",
        )


async def run() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )

    await init_db()
    lzt = LZTClient()

    logger.info("purchaser_started")
    while True:
        try:
            order = await _claim_order()
            if order is None:
                await asyncio.sleep(POLL_INTERVAL)
                continue
            await process_order(lzt, order)
        except Exception as exc:
            logger.error("purchaser_loop_error", error=str(exc), exc_info=True)
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
