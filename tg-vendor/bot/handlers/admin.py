from decimal import Decimal

import structlog
from aiogram import Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message

from core.balance import credit_deposit, get_balance
from core.config import settings
from core.db import get_conn
from core.lzt import LZTClient

logger = structlog.get_logger(__name__)
router = Router(name="admin")


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in settings.admin_tg_ids


router.message.filter(IsAdmin())


@router.message(Command("match_deposit"))
async def cmd_match_deposit(message: Message) -> None:
    """Manually credit an unmatched deposit.
    Usage: /match_deposit <tx_hash> <tg_id>
    """
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("사용법: /match_deposit &lt;tx_hash&gt; &lt;tg_id&gt;")
        return

    tx_hash, tg_id_str = parts[1].strip(), parts[2].strip()
    try:
        tg_id = int(tg_id_str)
    except ValueError:
        await message.answer("❌ tg_id는 숫자여야 합니다")
        return

    async with get_conn() as db:
        unmatched = await (
            await db.execute(
                "SELECT * FROM unmatched_deposits WHERE tx_hash = ?", (tx_hash,)
            )
        ).fetchone()

    if unmatched is None:
        await message.answer(f"❌ 미매칭 입금을 찾을 수 없습니다: <code>{tx_hash}</code>")
        return

    async with get_conn() as db:
        user = await (
            await db.execute("SELECT tg_id FROM users WHERE tg_id = ?", (tg_id,))
        ).fetchone()

    if user is None:
        await message.answer(f"❌ 사용자를 찾을 수 없습니다: {tg_id}")
        return

    from datetime import datetime, timezone
    block_ts_ms = int(
        datetime.fromisoformat(unmatched["block_ts"]).timestamp() * 1000
    )

    credited = await credit_deposit(
        user_id=tg_id,
        tx_hash=tx_hash,
        from_address=unmatched["from_address"],
        to_address=settings.deposit_address,
        amount=Decimal(unmatched["amount"]),
        block_ts_ms=block_ts_ms,
    )

    if not credited:
        await message.answer("⚠️ 이미 처리된 입금입니다 (중복)")
        return

    async with get_conn() as db:
        await db.execute("DELETE FROM unmatched_deposits WHERE tx_hash = ?", (tx_hash,))
        await db.commit()

    balance = await get_balance(tg_id)
    await message.answer(
        f"✅ 수동 매칭 완료\n"
        f"TX: <code>{tx_hash}</code>\n"
        f"사용자: {tg_id}\n"
        f"금액: {unmatched['amount']} USDT\n"
        f"잔액: <b>{balance:.4f} USDT</b>"
    )


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
    async with get_conn() as db:
        users_count = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        delivered = (await (await db.execute("SELECT COUNT(*) FROM orders WHERE status='DELIVERED'")).fetchone())[0]
        failed = (await (await db.execute("SELECT COUNT(*) FROM orders WHERE status='FAILED'")).fetchone())[0]
        revenue_row = await (await db.execute("SELECT COALESCE(SUM(CAST(price_paid AS REAL)),0) FROM orders WHERE status='DELIVERED'")).fetchone()
        balance_row = await (await db.execute("SELECT COALESCE(SUM(CAST(balance_usdt AS REAL)),0) FROM users")).fetchone()
        unmatched = (await (await db.execute("SELECT COUNT(*) FROM unmatched_deposits")).fetchone())[0]

    await message.answer(
        "📊 <b>통계</b>\n\n"
        f"<blockquote>"
        f"👤 사용자: {users_count}명\n"
        f"✅ 완료 주문: {delivered}건\n"
        f"❌ 실패 주문: {failed}건\n"
        f"💰 총 매출: {revenue_row[0]:.4f} USDT\n"
        f"💎 사용자 총 잔액: {balance_row[0]:.4f} USDT\n"
        f"⚠️ 미매칭 입금: {unmatched}건"
        f"</blockquote>"
    )


@router.message(Command("admin_unmatched"))
async def cmd_admin_unmatched(message: Message) -> None:
    async with get_conn() as db:
        rows = await (
            await db.execute(
                "SELECT tx_hash, from_address, amount, created_at FROM unmatched_deposits ORDER BY created_at DESC LIMIT 20"
            )
        ).fetchall()

    if not rows:
        await message.answer("✅ 미매칭 입금 없음")
        return

    lines = ["⚠️ <b>미매칭 입금 목록</b>\n"]
    for r in rows:
        short = r["tx_hash"][:12] + "..."
        lines.append(f"• <code>{short}</code> | {r['from_address'][:12]}... | {r['amount']} USDT")
    await message.answer("\n".join(lines))
