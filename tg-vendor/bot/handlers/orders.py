import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.templates import msg_orders_list, msg_resend_cooldown, msg_resend_success
from core.cache import cache_get, cache_set
from core.db import get_conn
from core.lzt import LZTClient

logger = structlog.get_logger(__name__)
router = Router(name="orders")

RESEND_COOLDOWN_TTL = 1800


@router.message(F.text == "📦 내 주문")
@router.message(Command("orders"))
async def cmd_orders(message: Message) -> None:
    async with get_conn() as db:
        rows = await (
            await db.execute(
                """
                SELECT id, item_id, price_paid, status, created_at, delivered_at
                FROM orders
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 10
                """,
                (message.from_user.id,),
            )
        ).fetchall()
    await message.answer(msg_orders_list([dict(r) for r in rows]))


@router.message(Command("resend"))
async def cmd_resend(message: Message) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer("사용법: /resend &lt;주문번호&gt;")
        return

    order_id = parts[1].strip()
    cooldown_key = f"resend:{order_id}"

    if cache_get(cooldown_key) is not None:
        await message.answer(msg_resend_cooldown())
        return

    async with get_conn() as db:
        order = await (
            await db.execute(
                """
                SELECT id, user_id, item_id, status
                FROM orders
                WHERE id = ? AND user_id = ? AND status = 'DELIVERED'
                """,
                (order_id, message.from_user.id),
            )
        ).fetchone()

    if order is None:
        await message.answer("❌ 주문을 찾을 수 없거나 배달 완료 상태가 아닙니다.")
        return

    lzt = LZTClient()
    try:
        result = await lzt.request_login_code(order["item_id"])
        login_code = result.get("telegram_login_code") or result.get("code", "")
    except Exception as e:
        logger.error("resend_failed", order_id=order_id, error=str(e))
        await message.answer("❌ 인증번호 재발급에 실패했습니다.")
        return

    if not login_code:
        await message.answer("❌ 인증번호를 받지 못했습니다.")
        return

    async with get_conn() as db:
        await db.execute(
            "UPDATE orders SET login_code = ? WHERE id = ?", (login_code, order_id)
        )
        await db.commit()

    cache_set(cooldown_key, "1", RESEND_COOLDOWN_TTL)
    await message.answer(msg_resend_success(login_code))
