"""Polls TronGrid for USDT deposits and credits matched users."""
import asyncio
import json
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


async def _load_cursor() -> int:
    async with get_conn() as db:
        row = await (
            await db.execute("SELECT last_block_ts FROM tron_cursor WHERE id = 1")
        ).fetchone()
    return int(row["last_block_ts"]) if row else 0


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

        # Find user by sender_address
        async with get_conn() as db:
            user = await (
                await db.execute(
                    "SELECT tg_id, balance_usdt FROM users WHERE LOWER(sender_address) = LOWER(?)",
                    (from_addr,),
                )
            ).fetchone()

        if user is None:
            await _log_unmatched(tx_hash, from_addr, amount, block_ts, tx)
            await _notify_admins(
                f"⚠️ <b>미매칭 입금 감지</b>\n\n"
                f"주소: <code>{from_addr}</code>\n"
                f"금액: {amount} USDT\n"
                f"TX: <code>{tx_hash}</code>\n\n"
                f"/match_deposit {tx_hash} &lt;tg_id&gt;"
            )
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
            # Get updated balance
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
            try:
                await poll_once(tron)
            except Exception as exc:
                logger.error("poll_error", error=str(exc), exc_info=True)
            await asyncio.sleep(settings.tron_poll_sec)
    finally:
        await tron.aclose()


if __name__ == "__main__":
    asyncio.run(run())
