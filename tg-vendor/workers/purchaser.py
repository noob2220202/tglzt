"""Processes purchase orders from the Redis queue."""
import asyncio
import json
from decimal import Decimal

import httpx
import structlog

from core.balance import refund_order
from core.cache import close_redis, init_redis, cache_delete, get_redis
from core.config import settings
from core.db import close_pool, init_pool
from core.lzt import LZTClient

logger = structlog.get_logger(__name__)

ORDER_QUEUE_KEY = "order:purchase"
LZT_BALANCE_CACHE_KEY = "lzt:balance"


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


async def process_order(pool, lzt: LZTClient, order_id: str) -> None:
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)

    if order is None:
        logger.error("order_not_found", order_id=order_id)
        return

    user_id = order["user_id"]
    item_id = order["item_id"]
    lzt_price = float(order["lzt_price_usd"])

    logger.info("processing_order", order_id=order_id, user_id=user_id, item_id=item_id)

    # Mark as PURCHASING
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE orders SET status = 'PURCHASING' WHERE id = $1 AND status = 'PENDING'",
            order_id,
        )

    try:
        # Check LZT balance
        lzt_balance = await lzt.get_balance()
        if lzt_balance < settings.lzt_balance_min_usd:
            await _notify_admins(
                f"🚨 <b>LZT 잔액 부족</b>\n\n현재 잔액: {lzt_balance:.2f} USD\n즉시 충전이 필요합니다"
            )
            raise RuntimeError(f"LZT 잔액 부족: {lzt_balance:.2f} USD")

        # Execute fast_buy
        buy_result = await lzt.fast_buy(item_id, lzt_price)
        logger.info("fast_buy_result", order_id=order_id, result_keys=list(buy_result.keys()))

        if not buy_result or buy_result.get("status") == 0:
            error_msg = buy_result.get("message", "Unknown LZT error") if buy_result else "Empty response"
            raise RuntimeError(f"fast_buy 실패: {error_msg}")

        item_data = buy_result.get("item", buy_result)

        # Extract phone number
        phone = (
            item_data.get("account_phone_number")
            or item_data.get("phone")
            or item_data.get("login")
            or ""
        )

        # Extract 2FA
        twofa = (
            item_data.get("account_password")
            or item_data.get("twofa_password")
            or item_data.get("password")
            or ""
        )

        # Get login code (retry up to 3 times with 5s delay)
        login_code = ""
        for attempt in range(3):
            try:
                code_result = await lzt.request_login_code(item_id)
                login_code = (
                    code_result.get("telegram_login_code")
                    or code_result.get("code")
                    or ""
                )
                if login_code:
                    break
            except Exception as exc:
                logger.warning("login_code_attempt_failed", attempt=attempt, error=str(exc))
            if attempt < 2:
                await asyncio.sleep(5)

        # Download session file if available
        session_url = (
            item_data.get("account_session_file")
            or item_data.get("session_file_url")
            or ""
        )
        session_path = ""
        session_bytes = None

        if session_url:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(session_url, timeout=30.0)
                    if resp.status_code == 200:
                        session_bytes = resp.content
                        session_path = f"session_{item_id}.session"
            except Exception as exc:
                logger.warning("session_download_failed", url=session_url, error=str(exc))

        # Mark as DELIVERED
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE orders
                SET status = 'DELIVERED',
                    phone = $2,
                    login_code = $3,
                    twofa_password = $4,
                    session_path = $5,
                    delivered_at = NOW()
                WHERE id = $1
                """,
                order_id,
                phone,
                login_code,
                twofa or None,
                session_path or None,
            )

        # Invalidate LZT balance cache
        await cache_delete(LZT_BALANCE_CACHE_KEY)

        # Send delivery message to user
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

        # Send session file if available
        if session_bytes and session_path:
            await _send_document(
                user_id,
                session_bytes,
                session_path,
                f"📁 세션 파일 - 주문 {order_id[:8]}",
            )

        logger.info("order_delivered", order_id=order_id, user_id=user_id)

    except Exception as exc:
        logger.error("order_failed", order_id=order_id, error=str(exc), exc_info=True)

        # Set FAILED status + fail_reason, then refund balance atomically
        async with pool.acquire() as conn:
            async with conn.transaction():
                order_row = await conn.fetchrow(
                    "SELECT user_id, price_paid, status FROM orders WHERE id = $1 FOR UPDATE",
                    order_id,
                )
                if order_row and order_row["status"] in ("PENDING", "PURCHASING"):
                    await conn.execute(
                        "UPDATE orders SET status = 'FAILED', fail_reason = $2 WHERE id = $1",
                        order_id,
                        str(exc)[:500],
                    )
                    await conn.execute(
                        "UPDATE users SET balance_usdt = balance_usdt + $1 WHERE tg_id = $2",
                        order_row["price_paid"],
                        order_row["user_id"],
                    )

            row = await conn.fetchrow(
                "SELECT balance_usdt FROM users WHERE tg_id = $1", user_id
            )
        new_balance = row["balance_usdt"] if row else Decimal("0")

        fail_text = (
            "❌ <b>구매에 실패했습니다</b>\n\n"
            "<blockquote>"
            f"사유: {str(exc)[:200]}\n"
            f"주문번호: <code>{order_id}</code>\n\n"
            "💰 잔액이 자동 환불되었습니다\n"
            f"현재 잔액: <b>{new_balance:.4f} USDT</b>"
            "</blockquote>\n\n"
            "<i>다른 매물을 선택해주세요</i>"
        )
        await _send_message(user_id, fail_text)


async def run() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )

    pool = await init_pool()
    await init_redis()
    lzt = LZTClient()

    logger.info("purchaser_started")
    try:
        r = get_redis()
        while True:
            try:
                result = await r.blpop(ORDER_QUEUE_KEY, timeout=5)
                if result is None:
                    continue
                order_id = result[1]
                await process_order(pool, lzt, order_id)
            except Exception as exc:
                logger.error("purchaser_error", error=str(exc), exc_info=True)
                await asyncio.sleep(1)
    finally:
        await close_redis()
        await close_pool()


if __name__ == "__main__":
    asyncio.run(run())
