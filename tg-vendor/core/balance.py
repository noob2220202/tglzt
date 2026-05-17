import uuid
from decimal import Decimal
from typing import Any

import structlog

from core.db import get_conn

logger = structlog.get_logger(__name__)


async def credit_deposit(
    user_id: int,
    tx_hash: str,
    from_address: str,
    to_address: str,
    amount: Decimal,
    block_ts_ms: int,
) -> bool:
    """Credit deposit atomically. Returns False if tx_hash already processed."""
    from datetime import datetime, timezone
    block_dt = datetime.fromtimestamp(block_ts_ms / 1000, tz=timezone.utc).isoformat()

    async with get_conn() as db:
        # Try to insert deposit (UNIQUE on tx_hash)
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO deposits
              (id, user_id, tx_hash, from_address, to_address, amount, block_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), user_id, tx_hash, from_address, to_address, str(amount), block_dt),
        )
        if cursor.rowcount == 0:
            return False  # duplicate

        await db.execute(
            "UPDATE users SET balance_usdt = CAST(CAST(balance_usdt AS REAL) + ? AS TEXT) WHERE tg_id = ?",
            (float(amount), user_id),
        )
        await db.commit()

    logger.info("deposit_credited", user_id=user_id, amount=str(amount), tx_hash=tx_hash)
    return True


async def debit_balance(user_id: int, amount: Decimal) -> bool:
    """Atomically debit balance. Returns False if insufficient.
    Uses UPDATE ... WHERE balance_usdt >= amount for atomic check-and-deduct."""
    async with get_conn() as db:
        cursor = await db.execute(
            """
            UPDATE users
            SET balance_usdt = CAST(CAST(balance_usdt AS REAL) - ? AS TEXT),
                total_spent   = CAST(CAST(total_spent AS REAL) + ? AS TEXT)
            WHERE tg_id = ? AND CAST(balance_usdt AS REAL) >= ?
            """,
            (float(amount), float(amount), user_id, float(amount)),
        )
        await db.commit()
        return cursor.rowcount > 0


async def refund_order(order_id: str) -> Decimal:
    """Refund order price to user. Returns refunded amount."""
    async with get_conn() as db:
        row = await (
            await db.execute(
                "SELECT user_id, price_paid, status FROM orders WHERE id = ?", (order_id,)
            )
        ).fetchone()

        if row is None or row["status"] not in ("PENDING", "PURCHASING", "FAILED"):
            return Decimal("0")

        amount = Decimal(row["price_paid"])
        await db.execute(
            "UPDATE orders SET status = 'REFUNDED' WHERE id = ?", (order_id,)
        )
        await db.execute(
            "UPDATE users SET balance_usdt = CAST(CAST(balance_usdt AS REAL) + ? AS TEXT) WHERE tg_id = ?",
            (float(amount), row["user_id"]),
        )
        await db.commit()

    logger.info("order_refunded", order_id=order_id, amount=str(amount))
    return amount


async def get_balance(user_id: int) -> Decimal:
    async with get_conn() as db:
        row = await (
            await db.execute("SELECT balance_usdt FROM users WHERE tg_id = ?", (user_id,))
        ).fetchone()
    return Decimal(row["balance_usdt"]) if row else Decimal("0")


async def get_user(user_id: int) -> dict[str, Any] | None:
    async with get_conn() as db:
        row = await (
            await db.execute("SELECT * FROM users WHERE tg_id = ?", (user_id,))
        ).fetchone()
    return dict(row) if row else None


async def count_user_orders(user_id: int) -> int:
    async with get_conn() as db:
        row = await (
            await db.execute(
                "SELECT COUNT(*) AS cnt FROM orders WHERE user_id = ? AND status = 'DELIVERED'",
                (user_id,),
            )
        ).fetchone()
    return row["cnt"] if row else 0
