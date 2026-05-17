# 텔레그램 계정 자판기 봇

lzt.market 드롭쉬핑 기반 텔레그램 계정 자동판매 봇.

## 구성

- **bot** — aiogram 3.x 봇 본체
- **inventory_cacher** — 30초마다 lzt `/telegram` 조회 → Redis 캐시
- **tron_watcher** — TronGrid 폴링으로 USDT TRC20 입금 자동 감지
- **purchaser** — 주문 큐 컨슈머, lzt fast_buy 처리

## 시작하기

```bash
cp .env.example .env
# .env 편집: 모든 필수 값 입력

docker compose up --build
```

## DB 마이그레이션 수동 실행

```bash
docker compose run --rm bot alembic upgrade head
```

## 환경 변수

| 변수 | 설명 |
|------|------|
| `BOT_TOKEN` | Telegram Bot API 토큰 |
| `ADMIN_TG_IDS` | 어드민 텔레그램 ID (쉼표 구분) |
| `LZT_TOKEN` | LOLZTEAM API 토큰 |
| `TRONGRID_API_KEY` | TronGrid API 키 |
| `DEPOSIT_ADDRESS` | 운영자 USDT TRC20 입금주소 |
| `USDT_CONTRACT` | USDT TRC20 컨트랙트 주소 |
| `DB_URL` | PostgreSQL 연결 문자열 |
| `REDIS_URL` | Redis 연결 문자열 |
| `MARKUP_PCT` | 마크업 비율 (기본: 0.25 = 25%) |
| `LZT_BALANCE_MIN_USD` | lzt 잔액 최소값 (미만 시 구매 차단) |
