from typing import Any

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

ITEMS_PER_PAGE = 8


def kb_main() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛒 매물보기"), KeyboardButton(text="💰 충전하기")],
            [KeyboardButton(text="📦 내 주문"), KeyboardButton(text="⚙️ 설정")],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def kb_remove() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def kb_register() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 주소 등록하기", callback_data="register_address")]
        ]
    )


def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ 취소", callback_data="cancel")]
        ]
    )


def kb_item_list(items: list[dict[str, Any]], page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start = page * ITEMS_PER_PAGE
    page_items = items[start : start + ITEMS_PER_PAGE]

    for item in page_items:
        item_id = item.get("item_id", 0)
        price = item.get("sell_price", 0)
        country = item.get("country", "??")
        premium = "💎" if item.get("premium") else ""
        label = f"📱 {country} {premium} · {price:.2f} USDT"
        builder.button(text=label, callback_data=f"item:{item_id}")

    builder.adjust(1)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ 이전", callback_data=f"page:{page-1}"))
    if start + ITEMS_PER_PAGE < len(items):
        nav.append(InlineKeyboardButton(text="다음 ➡️", callback_data=f"page:{page+1}"))
    if nav:
        builder.row(*nav)

    return builder.as_markup()


def kb_item_detail(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚡ 즉시구매", callback_data=f"buy:{item_id}"),
                InlineKeyboardButton(text="⬅️ 뒤로", callback_data="catalog:back"),
            ]
        ]
    )


def kb_deposit() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 잔액 새로고침", callback_data="balance:refresh")]
        ]
    )


def kb_go_deposit() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 충전하기", callback_data="balance:show")]
        ]
    )
