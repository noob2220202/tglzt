from decimal import Decimal

import structlog
from aiogram import Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message

from bot.templates import msg_admin_deposit_matched
from core.balance import credit_deposit, get_balance
from core.config import settings
from core.db import get_pool
from core.lzt import LZTClient

logger = structlog.get_logger(__name__)
router = Router(name="admin")


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in settings.admin_tg_ids


router.message.filter(IsAdmin())


@router.message(Command("match_deposit"))
async def cmd_match_deposit(message: Message) -> None:
    """Manually credit an unmatched deposit to a user.
    Usage: /match_deposit <tx_hash> <tg_id>
    """
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("사용법: /match_deposit &lt;tx_hash&gt; &lt;tg_id&gt;")
        return

    tx_hash = parts[1].strip()
    try:
        tg_id = int(parts[2].strip())
    except ValueError:
        await message.answer("❌ tg_id는 숫자여야 합니다")
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        unmatched = await conn.fetchrow(
            "SELECT * FROM unmatched_deposits WHERE tx_hash = $1",
            tx_hash,
        )

    if unmatched is None:
        await message.answer(f"❌ 미매칭 입금을 찾을 수 없습니다: <code>{tx_hash}</code>")
        return

    # Check target user exists
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT tg_id FROM users WHERE tg_id = $1", tg_id)

    if user is None:
        await message.answer(f"❌ 사용자를 찾을 수 없습니다: {tg_id}")
        return

    credited = await credit_deposit(
        pool=pool,
        user_id=tg_id,
        tx_hash=tx_hash,
        from_address=unmatched["from_address"],
        to_address=settings.deposit_address,
        amount=unmatched["amount"],
        block_ts_ms=int(unmatched["block_ts"].timestamp() * 1000),
    )

    if not credited:
        await message.answer("⚠️ 이미 처리된 입금입니다 (중복)")
        return

    # Remove from unmatched
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM unmatched_deposits WHERE tx_hash = $1",
            tx_hash,
        )

    balance = await get_balance(pool, tg_id)
    await message.answer(
        msg_admin_deposit_matched(tx_hash, tg_id, str(unmatched["amount"]))
        + f"\n잔액: <b>{balance:.4f} USDT</b>"
    )
    logger.info("manual_match", tx_hash=tx_hash, tg_id=tg_id, amount=str(unmatched["amount"]))


@router.message(Command("admin_balance"))
async def cmd_admin_balance(message: Message) -> None:
    lzt = LZTClient()
    try:
        balance = await lzt.get_balance()
        await message.answer(
            f"💰 <b>LZT 잔액</b>\n\n<blockquote>{balance:.2f} USD</blockquote>"
        )
    except Exception as e:
        await message.answer(f"❌ 잔액 조회 실패: {e}")


@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        users_count = await conn.fetchval("SELECT COUNT(*) FROM users")
        delivered = await conn.fetchval(
            "SELECT COUNT(*) FROM orders WHERE status = 'DELIVERED'"
        )
        failed = await conn.fetchval(
            "SELECT COUNT(*) FROM orders WHERE status = 'FAILED'"
        )
        total_revenue = await conn.fetchval(
            "SELECT COALESCE(SUM(price_paid), 0) FROM orders WHERE status = 'DELIVERED'"
        )
        pending_balance = await conn.fetchval(
            "SELECT COALESCE(SUM(balance_usdt), 0) FROM users"
        )
        unmatched_count = await conn.fetchval("SELECT COUNT(*) FROM unmatched_deposits")

    await message.answer(
        "📊 <b>통계</b>\n\n"
        f"<blockquote>"
        f"👤 사용자: {users_count}명\n"
        f"✅ 완료 주문: {delivered}건\n"
        f"❌ 실패 주문: {failed}건\n"
        f"💰 총 매출: {total_revenue:.4f} USDT\n"
        f"💎 사용자 총 잔액: {pending_balance:.4f} USDT\n"
        f"⚠️ 미매칭 입금: {unmatched_count}건"
        f"</blockquote>"
    )


@router.message(Command("admin_unmatched"))
async def cmd_admin_unmatched(message: Message) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT tx_hash, from_address, amount, created_at FROM unmatched_deposits ORDER BY created_at DESC LIMIT 20"
        )

    if not rows:
        await message.answer("✅ 미매칭 입금 없음")
        return

    lines = ["⚠️ <b>미매칭 입금 목록</b>\n"]
    for r in rows:
        short = r["tx_hash"][:12] + "..."
        lines.append(f"• <code>{short}</code> | {r['from_address'][:12]}... | {r['amount']} USDT")

    await message.answer("\n".join(lines))
