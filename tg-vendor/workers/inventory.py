"""Fetches telegram account listings from LZT and stores in SQLite inventory_cache."""
import asyncio
import json
from decimal import Decimal

import structlog

from core.config import settings
from core.db import get_conn, init_db
from core.lzt import LZTClient
from core.markup import calc_sell_price

logger = structlog.get_logger(__name__)


def _enrich_item(raw: dict) -> dict:
    lzt_price = Decimal(str(raw.get("price_usd") or raw.get("price") or "0"))
    sell_price = calc_sell_price(lzt_price)
    return {
        "item_id": raw.get("item_id") or raw.get("id"),
        "category": raw.get("category", "telegram"),
        "lzt_price_usd": float(lzt_price),
        "sell_price": float(sell_price),
        "country": raw.get("country") or raw.get("item_origin") or "",
        "premium": bool(raw.get("account_premium") or raw.get("premium")),
        "spam_block": bool(raw.get("is_spam") or raw.get("spam_block")),
        "title": raw.get("title") or raw.get("subject") or f"Telegram #{raw.get('item_id') or raw.get('id')}",
        "description": raw.get("description") or "",
        "created": str(raw.get("account_reg_date") or raw.get("created_at") or ""),
    }


async def refresh_once(lzt: LZTClient) -> None:
    all_items = []
    page = 1
    while True:
        try:
            raw_items = await lzt.get_telegram_items(page=page)
        except Exception as exc:
            logger.error("lzt_fetch_error", page=page, error=str(exc))
            break

        if not raw_items:
            break

        all_items.extend(_enrich_item(i) for i in raw_items)

        if len(raw_items) < 50:
            break
        page += 1

    if not all_items:
        logger.warning("inventory_empty")
        return

    async with get_conn() as db:
        await db.executemany(
            """
            INSERT INTO inventory_cache
              (item_id, category, price_usd, sell_price, country,
               premium, spam_block, title, raw_json, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(item_id) DO UPDATE SET
              price_usd  = excluded.price_usd,
              sell_price = excluded.sell_price,
              country    = excluded.country,
              premium    = excluded.premium,
              spam_block = excluded.spam_block,
              title      = excluded.title,
              raw_json   = excluded.raw_json,
              last_seen  = datetime('now')
            """,
            [
                (
                    item["item_id"],
                    item["category"],
                    str(item["lzt_price_usd"]),
                    str(item["sell_price"]),
                    item["country"],
                    int(item["premium"]),
                    int(item["spam_block"]),
                    item["title"],
                    json.dumps(item),
                )
                for item in all_items
                if item.get("item_id")
            ],
        )
        await db.commit()

    logger.info("inventory_refreshed", count=len(all_items))


async def run() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )

    await init_db()
    lzt = LZTClient()

    logger.info("inventory_cacher_started", refresh_sec=settings.inventory_refresh_sec)
    while True:
        try:
            await refresh_once(lzt)
        except Exception as exc:
            logger.error("refresh_error", error=str(exc), exc_info=True)
        await asyncio.sleep(settings.inventory_refresh_sec)


if __name__ == "__main__":
    asyncio.run(run())
