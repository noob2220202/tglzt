from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import asyncpg
import structlog

logger = structlog.get_logger(__name__)


async def credit_deposit(
    pool: asyncpg.Pool,
    user_id: int,
    tx_hash: str,
    from_address: str,
    to_address: str,
    amount: Decimal,
    block_ts_ms: int,
) -> bool:
    """Credit a deposit atomically. Returns False if tx_hash already processed."""
    block_dt = datetime.fromtimestamp(block_ts_ms / 1000, tz=timezone.utc)
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                await conn.execute(
                    """
                    INSERT INTO deposits (user_id, tx_hash, from_address, to_address,
                                         amount, block_ts)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    user_id,
                    tx_hash,
                    from_address,
                    to_address,
                    amount,
                    block_dt,
                )
            except asyncpg.UniqueViolationError:
                return False

            await conn.execute(
                "UPDATE users SET balance_usdt = balance_usdt + $1 WHERE tg_id = $2",
                amount,
                user_id,
            )
    logger.info("deposit credited", user_id=user_id, amount=str(amount), tx_hash=tx_hash)
    return True


async def debit_balance(
    conn: asyncpg.Connection,
    user_id: int,
    amount: Decimal,
) -> bool:
    """Deduct amount from user balance inside an existing transaction. Returns False if insufficient."""
    row = await conn.fetchrow(
        "SELECT balance_usdt FROM users WHERE tg_id = $1 FOR UPDATE",
        user_id,
    )
    if row is None or row["balance_usdt"] < amount:
        return False
    await conn.execute(
        "UPDATE users SET balance_usdt = balance_usdt - $1 WHERE tg_id = $2",
        amount,
        user_id,
    )
    return True


async def refund_order(pool: asyncpg.Pool, order_id: str) -> Decimal:
    """Refund order price to user. Marks order as REFUNDED. Returns refunded amount."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow(
                "SELECT user_id, price_paid, status FROM orders WHERE id = $1 FOR UPDATE",
                order_id,
            )
            if order is None or order["status"] not in ("PENDING", "PURCHASING", "FAILED"):
                return Decimal("0")

            amount = order["price_paid"]
            await conn.execute(
                "UPDATE orders SET status = 'REFUNDED' WHERE id = $1",
                order_id,
            )
            await conn.execute(
                "UPDATE users SET balance_usdt = balance_usdt + $1 WHERE tg_id = $2",
                amount,
                order["user_id"],
            )
    logger.info("order refunded", order_id=order_id, amount=str(amount))
    return amount


async def get_balance(pool: asyncpg.Pool, user_id: int) -> Decimal:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT balance_usdt FROM users WHERE tg_id = $1",
            user_id,
        )
    return row["balance_usdt"] if row else Decimal("0")


async def get_user(pool: asyncpg.Pool, user_id: int) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE tg_id = $1", user_id)
    return dict(row) if row else None


async def count_user_orders(pool: asyncpg.Pool, user_id: int) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM orders WHERE user_id = $1 AND status = 'DELIVERED'",
            user_id,
        )
    return row["cnt"] if row else 0
