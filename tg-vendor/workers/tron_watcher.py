"""Polls TronGrid only when users are actively waiting for deposits."""
import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import structlog

from core.balance import credit_deposit
from core.config import settings
from core.db import get_conn, init_db
from core.tron import TronGridClient

logger = structlog.get_logger(__name__)

REORG_BUFFER_MS = 60_000


async def _has_active_sessions() -> bool:
    """Return True if at least one user is waiting for a deposit."""
    async with get_conn() as db:
        row = await (
            await db.execute(
                "SELECT COUNT(*) FROM deposit_sessions WHERE expires_at > datetime('now')"
            )
        ).fetchone()
    return row[0] > 0


async def _cleanup_expired_sessions() -> None:
    async with get_conn() as db:
        await db.execute("DELETE FROM deposit_sessions WHERE expires_at <= datetime('now')")
        await db.commit()


async def _load_cursor() -> int:
    async with get_conn() as db:
        row = await (
            await db.execute("SELECT last_block_ts FROM tron_cursor WHERE id = 1")
        ).fetchone()
    ts = int(row["last_block_ts"]) if row else 0
    # Safety: never start from epoch — set to now if somehow 0
    if ts == 0:
        ts = int(time.time() * 1000) - 60_000
        await _save_cursor(ts)
    return ts


async def _save_cursor(ts_ms: int) -> None:
    async with get_conn() as db:
        await db.execute(
            """
            INSERT INTO tron_cursor (id, last_block_ts, updated_at)
            VALUES (1, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE
              SET last_block_ts = excluded.last_block_ts,
                  updated_at = datetime('now')
            """,
            (ts_ms,),
        )
        await db.commit()


async def _log_unmatched(tx_hash: str, from_addr: str, amount: Decimal, block_ts_ms: int, raw: dict) -> None:
    block_dt = datetime.fromtimestamp(block_ts_ms / 1000, tz=timezone.utc).isoformat()
    async with get_conn() as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO unmatched_deposits
              (id, tx_hash, from_address, amount, block_ts, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), tx_hash, from_addr, str(amount), block_dt, json.dumps(raw)),
        )
        await db.commit()


async def _notify(user_id: int, text: str) -> None:
    import httpx
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                json={"chat_id": user_id, "text": text, "parse_mode": "HTML"},
                timeout=10.0,
            )
        except Exception as exc:
            logger.warning("notify_failed", user_id=user_id, error=str(exc))


async def _notify_admins(text: str) -> None:
    import httpx
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


async def _remove_deposit_session(user_id: int) -> None:
    async with get_conn() as db:
        await db.execute("DELETE FROM deposit_sessions WHERE user_id = ?", (user_id,))
        await db.commit()


async def poll_once(tron: TronGridClient) -> None:
    cursor = await _load_cursor()
    min_ts = max(0, cursor - REORG_BUFFER_MS)

    txs = await tron.get_trc20_transfers(settings.deposit_address, min_ts)
    if not txs:
        return

    max_ts = cursor
    for tx in txs:
        if tx.get("type") != "Transfer":
            continue
        if tx.get("to", "").lower() != settings.deposit_address.lower():
            continue
        token_addr = tx.get("token_info", {}).get("address", "")
        if token_addr.lower() != settings.usdt_contract.lower():
            continue

        tx_hash = tx["transaction_id"]
        from_addr = tx["from"]
        amount = Decimal(int(tx.get("value", "0"))) / Decimal("1000000")
        block_ts = int(tx["block_timestamp"])

        if block_ts > max_ts:
            max_ts = block_ts

        async with get_conn() as db:
            user = await (
                await db.execute(
                    "SELECT tg_id FROM users WHERE LOWER(sender_address) = LOWER(?)",
                    (from_addr,),
                )
            ).fetchone()

        if user is None:
            # 미등록 주소는 DB에만 기록, 어드민 알림은 보내지 않음
            # (어드민은 /admin_unmatched 명령어로 확인)
            await _log_unmatched(tx_hash, from_addr, amount, block_ts, tx)
            logger.info("unmatched_deposit", from_addr=from_addr, amount=str(amount))
            continue

        credited = await credit_deposit(
            user_id=user["tg_id"],
            tx_hash=tx_hash,
            from_address=from_addr,
            to_address=settings.deposit_address,
            amount=amount,
            block_ts_ms=block_ts,
        )

        if credited:
            async with get_conn() as db:
                row = await (
                    await db.execute(
                        "SELECT balance_usdt FROM users WHERE tg_id = ?", (user["tg_id"],)
                    )
                ).fetchone()
            new_balance = Decimal(row["balance_usdt"]) if row else amount
            short_hash = tx_hash[:16] + "..."

            await _notify(
                user["tg_id"],
                f"✅ <b>입금이 확인되었습니다</b>\n\n"
                f"<blockquote>💎 입금액: <b>{amount:.4f} USDT</b>\n"
                f"💰 현재 잔액: {new_balance:.4f} USDT\n"
                f"🔗 TX: <code>{short_hash}</code></blockquote>\n\n"
                f"🛒 매물보기 버튼으로 구매를 시작하세요",
            )
            await _remove_deposit_session(user["tg_id"])
            logger.info("deposit_credited", user_id=user["tg_id"], amount=str(amount))

    if max_ts > cursor:
        await _save_cursor(max_ts - REORG_BUFFER_MS)


async def run() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )

    await init_db()
    tron = TronGridClient()

    logger.info("tron_watcher_started", poll_sec=settings.tron_poll_sec)
    try:
        while True:
            await _cleanup_expired_sessions()

            if await _has_active_sessions():
                try:
                    await poll_once(tron)
                except Exception as exc:
                    logger.error("poll_error", error=str(exc), exc_info=True)
            else:
                logger.info("no_active_sessions_skipping")

            await asyncio.sleep(settings.tron_poll_sec)
    finally:
        await tron.aclose()


if __name__ == "__main__":
    asyncio.run(run())
