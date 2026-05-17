import json
import uuid
from decimal import Decimal
from typing import Any

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
from core.cache import acquire_lock, cache_get, get_redis
from core.config import settings
from core.db import get_pool
from core.markup import calc_sell_price

logger = structlog.get_logger(__name__)
router = Router(name="purchase")

REDIS_INVENTORY_KEY = "inventory:items"
LZT_BALANCE_CACHE_KEY = "lzt:balance"
ORDER_QUEUE_KEY = "order:purchase"


async def _get_item_from_cache(item_id: int) -> dict[str, Any] | None:
    data = await cache_get(REDIS_INVENTORY_KEY)
    if not data:
        return None
    items = data if isinstance(data, list) else json.loads(data) if isinstance(data, str) else []
    return next((i for i in items if i.get("item_id") == item_id), None)


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    item_id = int(callback.data.split(":")[1])

    pool = get_pool()
    user = await get_user(pool, user_id)
    if user is None:
        await callback.message.answer(msg_not_registered())
        return

    item = await _get_item_from_cache(item_id)
    if item is None:
        await callback.message.answer("❌ 매물을 찾을 수 없습니다. 목록이 만료되었을 수 있습니다.")
        return

    sell_price = Decimal(str(item.get("sell_price", "0")))
    lzt_price = Decimal(str(item.get("lzt_price_usd", "0")))

    async with acquire_lock(f"purchase_lock:{user_id}", ttl_ms=5000) as acquired:
        if not acquired:
            await callback.message.answer("⏳ 이미 처리 중입니다. 잠시 후 다시 시도해주세요.")
            return

        # Check lzt balance from cache (60s TTL)
        lzt_bal_raw = await cache_get(LZT_BALANCE_CACHE_KEY)
        if lzt_bal_raw is not None:
            lzt_balance = Decimal(str(lzt_bal_raw))
            if lzt_balance < settings.lzt_balance_min_usd:
                await callback.message.answer(msg_lzt_unavailable())
                return

        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT balance_usdt FROM users WHERE tg_id = $1 FOR UPDATE",
                    user_id,
                )
                if row is None or row["balance_usdt"] < sell_price:
                    balance = row["balance_usdt"] if row else Decimal("0")
                    await callback.message.answer(
                        msg_insufficient_balance(sell_price, balance),
                        reply_markup=kb_go_deposit(),
                    )
                    return

                order_id = str(uuid.uuid4())
                await conn.execute(
                    """
                    INSERT INTO orders
                      (id, user_id, item_id, category, price_paid, lzt_price_usd, status)
                    VALUES ($1, $2, $3, $4, $5, $6, 'PENDING')
                    """,
                    order_id,
                    user_id,
                    item_id,
                    item.get("category", "telegram"),
                    sell_price,
                    lzt_price,
                )
                await conn.execute(
                    """
                    UPDATE users
                    SET balance_usdt = balance_usdt - $1,
                        total_spent = total_spent + $1
                    WHERE tg_id = $2
                    """,
                    sell_price,
                    user_id,
                )

        # Enqueue for purchaser worker
        await get_redis().rpush(ORDER_QUEUE_KEY, order_id)
        logger.info("order enqueued", order_id=order_id, user_id=user_id, item_id=item_id)

    await callback.message.answer(msg_purchasing())
