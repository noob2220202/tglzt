import json
from decimal import Decimal
from typing import Any

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.keyboards import kb_item_detail, kb_item_list
from bot.templates import msg_item_detail, msg_item_list_header, msg_not_registered
from core.balance import get_user
from core.cache import cache_get
from core.db import get_pool

logger = structlog.get_logger(__name__)
router = Router(name="catalog")

REDIS_INVENTORY_KEY = "inventory:items"


async def _load_items() -> list[dict[str, Any]]:
    data = await cache_get(REDIS_INVENTORY_KEY)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return []
    return []


@router.message(F.text == "🛒 매물보기")
async def btn_catalog(message: Message) -> None:
    user = await get_user(get_pool(), message.from_user.id)
    if user is None:
        await message.answer(msg_not_registered())
        return

    items = await _load_items()
    if not items:
        await message.answer(
            "📦 <b>현재 재고가 없습니다</b>\n\n<i>잠시 후 다시 확인해주세요</i>"
        )
        return

    await message.answer(
        msg_item_list_header(len(items)),
        reply_markup=kb_item_list(items, page=0),
    )


@router.callback_query(F.data.startswith("page:"))
async def cb_page(callback: CallbackQuery) -> None:
    await callback.answer()
    page = int(callback.data.split(":")[1])
    items = await _load_items()
    if not items:
        await callback.message.edit_text("📦 재고가 없습니다")
        return

    await callback.message.edit_text(
        msg_item_list_header(len(items)),
        reply_markup=kb_item_list(items, page=page),
    )


@router.callback_query(F.data.startswith("item:"))
async def cb_item_detail(callback: CallbackQuery) -> None:
    await callback.answer()
    item_id = int(callback.data.split(":")[1])

    user = await get_user(get_pool(), callback.from_user.id)
    if user is None:
        await callback.message.answer(msg_not_registered())
        return

    items = await _load_items()
    item = next((i for i in items if i.get("item_id") == item_id), None)
    if item is None:
        await callback.message.answer("❌ 매물을 찾을 수 없습니다. 목록을 새로고침해주세요.")
        return

    await callback.message.edit_text(
        msg_item_detail(item, user["balance_usdt"]),
        reply_markup=kb_item_detail(item_id),
    )


@router.callback_query(F.data == "catalog:back")
async def cb_catalog_back(callback: CallbackQuery) -> None:
    await callback.answer()
    items = await _load_items()
    if not items:
        await callback.message.edit_text("📦 재고가 없습니다")
        return

    await callback.message.edit_text(
        msg_item_list_header(len(items)),
        reply_markup=kb_item_list(items, page=0),
    )
