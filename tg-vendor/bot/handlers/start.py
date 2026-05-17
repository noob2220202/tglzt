import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards import kb_cancel, kb_main, kb_register
from bot.states import RegisterAddress
from bot.templates import (
    msg_address_duplicate,
    msg_address_error,
    msg_address_prompt,
    msg_address_success,
    msg_cancel,
    msg_home,
    msg_welcome_new,
)
from core.balance import count_user_orders, get_user
from core.db import get_pool
from core.tron import validate_trc20_address

logger = structlog.get_logger(__name__)
router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await get_user(get_pool(), message.from_user.id)

    if user is None:
        await message.answer(msg_welcome_new(), reply_markup=kb_register())
        return

    total = await count_user_orders(get_pool(), message.from_user.id)
    await message.answer(
        msg_home(
            username=message.from_user.username or message.from_user.first_name or "",
            balance=user["balance_usdt"],
            total_orders=total,
        ),
        reply_markup=kb_main(),
    )


@router.callback_query(F.data == "register_address")
async def btn_register_address(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(RegisterAddress.waiting)
    await callback.message.answer(msg_address_prompt(), reply_markup=kb_cancel())


@router.message(RegisterAddress.waiting, Command("cancel"))
@router.callback_query(RegisterAddress.waiting, F.data == "cancel")
async def cmd_cancel_registration(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(msg_cancel())
    else:
        await event.answer(msg_cancel())


@router.message(RegisterAddress.waiting)
async def process_address_input(message: Message, state: FSMContext) -> None:
    addr = (message.text or "").strip()

    if not validate_trc20_address(addr):
        await message.answer(msg_address_error(), reply_markup=kb_cancel())
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT tg_id FROM users WHERE sender_address = $1", addr
        )
        if existing and existing["tg_id"] != message.from_user.id:
            await message.answer(msg_address_duplicate(), reply_markup=kb_cancel())
            return

        user = await conn.fetchrow(
            "SELECT tg_id FROM users WHERE tg_id = $1", message.from_user.id
        )
        if user is None:
            await conn.execute(
                """
                INSERT INTO users (tg_id, username, sender_address)
                VALUES ($1, $2, $3)
                ON CONFLICT (tg_id) DO UPDATE
                  SET sender_address = EXCLUDED.sender_address,
                      username = EXCLUDED.username
                """,
                message.from_user.id,
                message.from_user.username or message.from_user.first_name,
                addr,
            )
        else:
            await conn.execute(
                "UPDATE users SET sender_address = $1 WHERE tg_id = $2",
                addr,
                message.from_user.id,
            )

    await state.clear()
    logger.info("address registered", user_id=message.from_user.id, address=addr)
    await message.answer(msg_address_success(addr), reply_markup=kb_main())


@router.message(Command("cancel"))
async def cmd_cancel_global(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(msg_cancel())
