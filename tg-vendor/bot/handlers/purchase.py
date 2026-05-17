import uuid
from decimal import Decimal

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.keyboards import kb_go_deposit
from bot.templates import (
    msg_insufficient_balance,
    msg_lzt_unavailable,
    msg_not_registered,
    msg_purchasing,
)
from core.balance import get_user
from core.cache import acquire_user_lock, cache_get
from core.config import settings
from core.db import get_conn
from core.markup import calc_sell_price

logger = structlog.get_logger(__name__)
router = Router(name="purchase")

LZT_BALANCE_CACHE_KEY = "lzt:balance"


async def _get_item(item_id: int) -> dict | None:
    from bot.handlers.catalog import _load_items
    items = await _load_items()
    return next((i for i in items if i.get("item_id") == item_id), None)


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    item_id = int(callback.data.split(":")[1])

    user = await get_user(user_id)
    if user is None:
        await callback.message.answer(msg_not_registered())
        return

    item = await _get_item(item_id)
    if item is None:
        await callback.message.answer("❌ 매물을 찾을 수 없습니다. 목록이 만료되었을 수 있습니다.")
        return

    lzt_price = Decimal(str(item.get("lzt_price_usd") or item.get("price_usd") or "0"))
    sell_price = calc_sell_price(lzt_price)

    async with acquire_user_lock(user_id) as acquired:
        if not acquired:
            await callback.message.answer("⏳ 이미 처리 중입니다. 잠시 후 다시 시도해주세요.")
            return

        # Check LZT balance (60s in-memory cache)
        lzt_bal_raw = cache_get(LZT_BALANCE_CACHE_KEY)
        if lzt_bal_raw is not None:
            if Decimal(str(lzt_bal_raw)) < settings.lzt_balance_min_usd:
                await callback.message.answer(msg_lzt_unavailable())
                return

        async with get_conn() as db:
            # Atomic debit: UPDATE only if balance >= sell_price
            cursor = await db.execute(
                """
                UPDATE users
                SET balance_usdt = CAST(CAST(balance_usdt AS REAL) - ? AS TEXT),
                    total_spent   = CAST(CAST(total_spent AS REAL) + ? AS TEXT)
                WHERE tg_id = ? AND CAST(balance_usdt AS REAL) >= ?
                """,
                (float(sell_price), float(sell_price), user_id, float(sell_price)),
            )

            if cursor.rowcount == 0:
                # Re-read balance to show accurate diff
                row = await (
                    await db.execute("SELECT balance_usdt FROM users WHERE tg_id = ?", (user_id,))
                ).fetchone()
                balance = Decimal(row["balance_usdt"]) if row else Decimal("0")
                await db.commit()
                await callback.message.answer(
                    msg_insufficient_balance(sell_price, balance),
                    reply_markup=kb_go_deposit(),
                )
                return

            order_id = str(uuid.uuid4())
            await db.execute(
                """
                INSERT INTO orders
                  (id, user_id, item_id, category, price_paid, lzt_price_usd, status)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
                """,
                (
                    order_id,
                    user_id,
                    item_id,
                    item.get("category", "telegram"),
                    str(sell_price),
                    str(lzt_price),
                ),
            )
            await db.commit()

    logger.info("order_created", order_id=order_id, user_id=user_id, item_id=item_id)
    await callback.message.answer(msg_purchasing())
