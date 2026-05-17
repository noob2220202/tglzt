"""Polls TronGrid for USDT TRC20 deposits to the operator's address, credits matched users."""
import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

import structlog

from core.balance import credit_deposit
from core.cache import init_redis, close_redis
from core.config import settings
from core.db import close_pool, init_pool
from core.tron import TronGridClient

logger = structlog.get_logger(__name__)

REORG_BUFFER_MS = 60_000


async def _load_cursor(pool) -> int:
    row = await pool.fetchrow("SELECT last_block_ts FROM tron_cursor WHERE id = 1")
    return int(row["last_block_ts"]) if row and row["last_block_ts"] else 0


async def _save_cursor(pool, ts_ms: int) -> None:
    await pool.execute(
        """
        INSERT INTO tron_cursor (id, last_block_ts, updated_at)
        VALUES (1, $1, NOW())
        ON CONFLICT (id) DO UPDATE
          SET last_block_ts = EXCLUDED.last_block_ts,
              updated_at = NOW()
        """,
        ts_ms,
    )


async def _log_unmatched(pool, tx_hash: str, from_addr: str, amount: Decimal, block_ts_ms: int, raw: dict) -> None:
    block_dt = datetime.fromtimestamp(block_ts_ms / 1000, tz=timezone.utc)
    try:
        await pool.execute(
            """
            INSERT INTO unmatched_deposits (tx_hash, from_address, amount, block_ts, raw_json)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (tx_hash) DO NOTHING
            """,
            tx_hash,
            from_addr,
            amount,
            block_dt,
            json.dumps(raw),
        )
    except Exception as e:
        logger.error("unmatched_log_error", error=str(e))


async def _notify_admins(bot_token: str, text: str) -> None:
    import httpx
    async with httpx.AsyncClient() as client:
        for admin_id in settings.admin_tg_ids:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": admin_id, "text": text, "parse_mode": "HTML"},
                    timeout=10.0,
                )
            except Exception as exc:
                logger.warning("admin_notify_failed", admin_id=admin_id, error=str(exc))


async def _notify_user(bot_token: str, user_id: int, amount: Decimal, balance: Decimal, tx_hash: str) -> None:
    import httpx
    short_hash = tx_hash[:16] + "..." if len(tx_hash) > 16 else tx_hash
    text = (
        "✅ <b>입금이 확인되었습니다</b>\n\n"
        f"<blockquote>💎 입금액: <b>{amount:.4f} USDT</b>\n"
        f"💰 현재 잔액: {balance:.4f} USDT\n"
        f"🔗 TX: <code>{short_hash}</code></blockquote>\n\n"
        "🛒 매물보기 버튼으로 구매를 시작하세요"
    )
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": user_id, "text": text, "parse_mode": "HTML"},
                timeout=10.0,
            )
        except Exception as exc:
            logger.warning("user_notify_failed", user_id=user_id, error=str(exc))


async def poll_once(pool, tron_client: TronGridClient) -> None:
    cursor = await _load_cursor(pool)
    min_ts = max(0, cursor - REORG_BUFFER_MS)

    txs = await tron_client.get_trc20_transfers(settings.deposit_address, min_ts)
    if not txs:
        return

    max_ts = cursor
    for tx in txs:
        if tx.get("type") != "Transfer":
            continue
        if tx.get("to", "").lower() != settings.deposit_address.lower():
            continue
        token_info = tx.get("token_info", {})
        if token_info.get("address", "").lower() != settings.usdt_contract.lower():
            continue

        tx_hash = tx["transaction_id"]
        from_addr = tx["from"]
        raw_value = int(tx.get("value", "0"))
        amount = Decimal(raw_value) / Decimal("1000000")
        block_ts = int(tx["block_timestamp"])

        if block_ts > max_ts:
            max_ts = block_ts

        # Find matching user
        user = await pool.fetchrow(
            "SELECT tg_id, balance_usdt FROM users WHERE LOWER(sender_address) = LOWER($1)",
            from_addr,
        )

        if user is None:
            await _log_unmatched(pool, tx_hash, from_addr, amount, block_ts, tx)
            await _notify_admins(
                settings.bot_token,
                f"⚠️ <b>미매칭 입금 감지</b>\n\n"
                f"주소: <code>{from_addr}</code>\n"
                f"금액: {amount} USDT\n"
                f"TX: <code>{tx_hash}</code>\n\n"
                f"/match_deposit {tx_hash} &lt;tg_id&gt;",
            )
            continue

        credited = await credit_deposit(
            pool=pool,
            user_id=user["tg_id"],
            tx_hash=tx_hash,
            from_address=from_addr,
            to_address=settings.deposit_address,
            amount=amount,
            block_ts_ms=block_ts,
        )

        if credited:
            # Get updated balance
            new_row = await pool.fetchrow(
                "SELECT balance_usdt FROM users WHERE tg_id = $1", user["tg_id"]
            )
            new_balance = new_row["balance_usdt"] if new_row else amount
            await _notify_user(settings.bot_token, user["tg_id"], amount, new_balance, tx_hash)
            logger.info("deposit_processed", user_id=user["tg_id"], amount=str(amount))

    if max_ts > cursor:
        await _save_cursor(pool, max_ts - REORG_BUFFER_MS)


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
    tron = TronGridClient()

    logger.info("tron_watcher_started", poll_sec=settings.tron_poll_sec)
    try:
        while True:
            try:
                await poll_once(pool, tron)
            except Exception as exc:
                logger.error("poll_error", error=str(exc), exc_info=True)
            await asyncio.sleep(settings.tron_poll_sec)
    finally:
        await tron.aclose()
        await close_redis()
        await close_pool()


if __name__ == "__main__":
    asyncio.run(run())
