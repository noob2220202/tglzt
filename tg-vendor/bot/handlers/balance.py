import io

import qrcode
import structlog
from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.keyboards import kb_deposit, kb_main
from bot.templates import msg_deposit_info, msg_not_registered
from core.balance import get_user
from core.config import settings
from core.db import get_pool

logger = structlog.get_logger(__name__)
router = Router(name="balance")


def _make_qr(data: str) -> BufferedInputFile:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return BufferedInputFile(buf.read(), filename="deposit_qr.png")


async def _send_deposit_info(target: Message | CallbackQuery) -> None:
    msg = target if isinstance(target, Message) else target.message
    user_id = (
        target.from_user.id if isinstance(target, Message) else target.from_user.id
    )

    user = await get_user(get_pool(), user_id)
    if user is None:
        await msg.answer(msg_not_registered())
        return

    text = msg_deposit_info(
        deposit_addr=settings.deposit_address,
        sender_addr=user["sender_address"] or "미등록",
        balance=user["balance_usdt"],
    )
    qr = _make_qr(settings.deposit_address)
    await msg.answer_photo(qr, caption=text, reply_markup=kb_deposit())


@router.message(F.text == "💰 충전하기")
async def btn_deposit(message: Message) -> None:
    await _send_deposit_info(message)


@router.callback_query(F.data == "balance:show")
async def cb_balance_show(callback: CallbackQuery) -> None:
    await callback.answer()
    await _send_deposit_info(callback)


@router.callback_query(F.data == "balance:refresh")
async def cb_balance_refresh(callback: CallbackQuery) -> None:
    await callback.answer("잔액을 새로고침했습니다")
    user = await get_user(get_pool(), callback.from_user.id)
    if user is None:
        await callback.message.answer(msg_not_registered())
        return

    text = msg_deposit_info(
        deposit_addr=settings.deposit_address,
        sender_addr=user["sender_address"] or "미등록",
        balance=user["balance_usdt"],
    )
    try:
        await callback.message.edit_caption(caption=text, reply_markup=kb_deposit())
    except Exception:
        qr = _make_qr(settings.deposit_address)
        await callback.message.answer_photo(qr, caption=text, reply_markup=kb_deposit())
