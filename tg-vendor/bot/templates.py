"""All user-facing HTML message templates."""
from decimal import Decimal
from typing import Any


def msg_welcome_new() -> str:
    return (
        "💎 <b>텔레그램 계정 자판기</b>\n\n"
        "<blockquote>⚡ 자동결제 · 즉시지급\n"
        "📱 다국적 계정 보유\n"
        "🔐 2FA 비밀번호 포함</blockquote>\n\n"
        "📌 <b>가입 안내</b>\n"
        "<i>USDT TRC20로 결제하는 자판기입니다\n"
        "시작하려면 본인 TRC20 송금주소를 등록해주세요</i>\n\n"
        "⚠️ <b>주의</b>\n"
        "<i>등록한 주소에서 보낸 입금만 인식됩니다\n"
        "거래소 주소 가능 (Binance, Bybit, OKX 등)\n"
        "다른 주소로 보내면 자산 손실 위험</i>"
    )


def msg_address_prompt() -> str:
    return (
        "📝 <b>본인 TRC20 주소 입력</b>\n\n"
        "<blockquote>USDT를 보낼 본인 주소를 입력해주세요\n"
        "거래소 출금주소 또는 개인지갑 주소\n\n"
        "예: TXYZabc...123 (T로 시작, 34자)</blockquote>\n\n"
        "❌ 취소하려면 /cancel"
    )


def msg_address_success(sender_address: str) -> str:
    return (
        "✅ <b>주소 등록 완료</b>\n\n"
        "<blockquote>📥 등록 주소\n"
        f"<code>{sender_address}</code></blockquote>\n\n"
        "이제 USDT를 입금할 수 있습니다\n"
        "💰 충전 메뉴로 이동해주세요"
    )


def msg_address_error() -> str:
    return (
        "❌ <b>잘못된 주소 형식</b>\n\n"
        "<i>TRC20 주소는 T로 시작하고 34자입니다\n"
        "다시 입력해주세요</i>"
    )


def msg_address_duplicate() -> str:
    return (
        "❌ <b>이미 등록된 주소입니다</b>\n\n"
        "<i>다른 사용자가 사용 중인 주소입니다\n"
        "본인 지갑 주소를 입력해주세요</i>"
    )


def msg_home(username: str, balance: Decimal, total_orders: int) -> str:
    display = username or "사용자"
    return (
        "💎 <b>텔레그램 계정 자판기</b>\n\n"
        "<blockquote>"
        f"👤 {display}\n"
        f"💰 잔액: <b>{balance:.4f} USDT</b>\n"
        f"📦 누적 구매: {total_orders}건"
        "</blockquote>\n\n"
        "<i>아래 메뉴에서 시작하세요</i>"
    )


def msg_deposit_info(deposit_addr: str, sender_addr: str, balance: Decimal) -> str:
    return (
        "💰 <b>USDT TRC20 충전</b>\n\n"
        "<blockquote>📥 입금 주소\n"
        f"<code>{deposit_addr}</code>\n\n"
        "📤 등록된 본인 주소\n"
        f"<code>{sender_addr}</code></blockquote>\n\n"
        "⚠️ <b>중요</b>\n"
        "<i>반드시 위 등록 주소에서만 보내주세요\n"
        "다른 주소에서 보내면 자동인식 안 됩니다\n"
        "TRC20 네트워크 필수</i>\n\n"
        f"💎 <b>현재 잔액: {balance:.4f} USDT</b>\n\n"
        "⏳ <i>입금 확인 보통 1~3분\n"
        "컨펌 즉시 자동 반영</i>"
    )


def msg_deposit_confirmed(amount: Decimal, balance: Decimal, tx_hash: str) -> str:
    short_hash = tx_hash[:16] + "..." if len(tx_hash) > 16 else tx_hash
    return (
        "✅ <b>입금이 확인되었습니다</b>\n\n"
        "<blockquote>"
        f"💎 입금액: <b>{amount:.4f} USDT</b>\n"
        f"💰 현재 잔액: {balance:.4f} USDT\n"
        f"🔗 TX: <code>{short_hash}</code>"
        "</blockquote>\n\n"
        "🛒 매물보기 버튼으로 구매를 시작하세요"
    )


def msg_item_list_header(total: int) -> str:
    return (
        "🛒 <b>텔레그램 계정 매물</b>\n\n"
        f"<blockquote>📦 현재 재고: {total}개</blockquote>\n\n"
        "<i>구매할 계정을 선택하세요</i>"
    )


def msg_item_detail(item: dict[str, Any], balance: Decimal) -> str:
    country = item.get("country", "알 수 없음")
    price = item.get("sell_price", Decimal("0"))
    premium = "있음" if item.get("premium") else "없음"
    spam = "있음" if item.get("spam_block") else "없음"
    created = item.get("created", "")
    desc = str(item.get("description", ""))[:100]
    title = item.get("title", f"계정 #{item.get('item_id', '')}")

    return (
        f"📱 <b>{title}</b>\n\n"
        "<blockquote>"
        f"🌍 국가: {country}\n"
        f"📅 가입일: {created}\n"
        f"💎 프리미엄: {premium}\n"
        f"🚫 스팸블록: {spam}\n"
        f"📝 설명: {desc}"
        "</blockquote>\n\n"
        f"💰 <b>가격: {price:.2f} USDT</b>\n"
        f"<i>현재 잔액: {balance:.4f} USDT</i>"
    )


def msg_purchasing() -> str:
    return (
        "⏳ <b>구매 진행중...</b>\n\n"
        "<blockquote>잠시만 기다려주세요\n"
        "보통 10~30초 소요</blockquote>"
    )


def msg_delivered(
    phone: str,
    login_code: str,
    twofa_password: str | None,
    order_id: str,
) -> str:
    twofa = twofa_password or "없음"
    return (
        "✅ <b>구매 완료!</b>\n\n"
        "<blockquote>"
        f"📱 전화번호\n<code>{phone}</code>\n\n"
        f"🔐 로그인 인증번호\n<code>{login_code}</code>\n\n"
        f"🔑 2FA 비밀번호\n<code>{twofa}</code>"
        "</blockquote>\n\n"
        "📖 <b>사용법</b>\n"
        "<i>1. 텔레그램 앱 → 전화번호 입력\n"
        "2. 위 인증번호 입력\n"
        "3. 2FA 비밀번호 있으면 입력\n"
        "4. 즉시 비번/번호 변경 권장</i>\n\n"
        "⚠️ <b>주의</b>\n"
        "<i>인증번호는 5분간만 유효\n"
        f"재발급은 /resend {order_id}</i>"
    )


def msg_insufficient_balance(price: Decimal, balance: Decimal) -> str:
    diff = price - balance
    return (
        "❌ <b>잔액이 부족합니다</b>\n\n"
        "<blockquote>"
        f"필요 금액: {price:.2f} USDT\n"
        f"현재 잔액: {balance:.4f} USDT\n"
        f"부족분: <b>{diff:.4f} USDT</b>"
        "</blockquote>\n\n"
        "💰 충전하기를 눌러주세요"
    )


def msg_purchase_failed(reason: str, order_id: str, balance: Decimal) -> str:
    return (
        "❌ <b>구매에 실패했습니다</b>\n\n"
        "<blockquote>"
        f"사유: {reason}\n"
        f"주문번호: <code>{order_id}</code>\n\n"
        f"💰 잔액이 자동 환불되었습니다\n"
        f"현재 잔액: <b>{balance:.4f} USDT</b>"
        "</blockquote>\n\n"
        "<i>다른 매물을 선택해주세요</i>"
    )


def msg_lzt_unavailable() -> str:
    return (
        "⏳ <b>일시적으로 구매가 제한됩니다</b>\n\n"
        "<blockquote>잠시 후 다시 시도해주세요\n"
        "이미 충전된 잔액은 그대로 유지됩니다</blockquote>"
    )


def msg_orders_list(orders: list[dict[str, Any]]) -> str:
    if not orders:
        return "📦 <b>주문 내역이 없습니다</b>"

    lines = ["📦 <b>최근 주문 내역</b>\n"]
    status_emoji = {
        "DELIVERED": "✅",
        "PENDING": "⏳",
        "PURCHASING": "🔄",
        "FAILED": "❌",
        "REFUNDED": "💰",
    }
    for o in orders:
        emoji = status_emoji.get(o["status"], "•")
        short_id = str(o["id"])[:8]
        lines.append(
            f"{emoji} <code>{short_id}</code> · {o['price_paid']:.2f} USDT · {o['status']}"
        )
    return "\n".join(lines)


def msg_cancel() -> str:
    return "❌ 취소되었습니다"


def msg_not_registered() -> str:
    return (
        "⚠️ <b>가입이 필요합니다</b>\n\n"
        "<i>/start 명령어로 가입을 완료해주세요</i>"
    )


def msg_resend_success(login_code: str) -> str:
    return (
        "✅ <b>인증번호가 재발급되었습니다</b>\n\n"
        f"<blockquote>🔐 새 인증번호\n<code>{login_code}</code></blockquote>\n\n"
        "<i>5분 내에 입력해주세요</i>"
    )


def msg_resend_cooldown() -> str:
    return (
        "⏳ <b>재발급 대기중</b>\n\n"
        "<i>30분에 1회만 재발급 가능합니다</i>"
    )


def msg_admin_deposit_matched(tx_hash: str, user_id: int, amount: str) -> str:
    return (
        f"✅ 수동 매칭 완료\n"
        f"TX: <code>{tx_hash}</code>\n"
        f"사용자: {user_id}\n"
        f"금액: {amount} USDT"
    )


def msg_admin_unmatched_deposit(from_addr: str, amount: str, tx_hash: str) -> str:
    return (
        "⚠️ <b>미매칭 입금 감지</b>\n\n"
        f"<blockquote>주소: <code>{from_addr}</code>\n"
        f"금액: {amount} USDT\n"
        f"TX: <code>{tx_hash}</code></blockquote>\n\n"
        f"/match_deposit {tx_hash} &lt;tg_id&gt;"
    )


def msg_admin_lzt_low_balance(balance: str) -> str:
    return (
        "🚨 <b>LZT 잔액 부족 경고</b>\n\n"
        f"<blockquote>현재 잔액: {balance} USD</blockquote>\n\n"
        "<i>즉시 충전이 필요합니다</i>"
    )
