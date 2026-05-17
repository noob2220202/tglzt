"""Periodically fetches telegram account listings from LZT and caches them in Redis."""
import asyncio
import json
from decimal import Decimal

import structlog

from core.cache import cache_set, init_redis, close_redis
from core.config import settings
from core.db import close_pool, init_pool
from core.lzt import LZTClient
from core.markup import calc_sell_price

logger = structlog.get_logger(__name__)

REDIS_INVENTORY_KEY = "inventory:items"
REDIS_ITEM_KEY_PREFIX = "inventory:item:"
CACHE_TTL = 300  # 5 minutes


def _enrich_item(raw: dict) -> dict:
    """Add computed sell_price and normalise fields for the bot."""
    lzt_price = Decimal(str(raw.get("price_usd") or raw.get("price") or "0"))
    sell_price = calc_sell_price(lzt_price)

    return {
        "item_id": raw.get("item_id") or raw.get("id"),
        "category": raw.get("category", "telegram"),
        "lzt_price_usd": float(lzt_price),
        "sell_price": float(sell_price),
        "country": raw.get("country") or raw.get("item_origin"),
        "premium": bool(raw.get("account_premium") or raw.get("premium")),
        "spam_block": bool(raw.get("is_spam") or raw.get("spam_block")),
        "title": raw.get("title") or raw.get("subject") or f"Telegram #{raw.get('item_id') or raw.get('id')}",
        "description": raw.get("description") or "",
        "created": str(raw.get("account_reg_date") or raw.get("created_at") or ""),
    }


async def refresh_once(lzt: LZTClient, pool) -> None:
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

        enriched = [_enrich_item(item) for item in raw_items]
        all_items.extend(enriched)

        if len(raw_items) < 50:
            break
        page += 1

    if not all_items:
        logger.warning("inventory_empty")
        return

    # Store list in Redis
    await cache_set(REDIS_INVENTORY_KEY, json.dumps(all_items), CACHE_TTL)

    # Per-item cache
    for item in all_items:
        item_id = item.get("item_id")
        if item_id:
            await cache_set(f"{REDIS_ITEM_KEY_PREFIX}{item_id}", json.dumps(item), CACHE_TTL)

    # Upsert into DB for audit trail
    if pool:
        import json as _json
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO inventory_cache (item_id, category, price_usd, country,
                    premium, spam_block, raw_json, last_seen)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                ON CONFLICT (item_id) DO UPDATE
                  SET price_usd = EXCLUDED.price_usd,
                      country = EXCLUDED.country,
                      premium = EXCLUDED.premium,
                      spam_block = EXCLUDED.spam_block,
                      raw_json = EXCLUDED.raw_json,
                      last_seen = NOW()
                """,
                [
                    (
                        item["item_id"],
                        item["category"],
                        item["lzt_price_usd"],
                        item["country"],
                        item["premium"],
                        item["spam_block"],
                        _json.dumps(item),
                    )
                    for item in all_items
                    if item.get("item_id")
                ],
            )

    logger.info("inventory_refreshed", count=len(all_items))


async def run() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ]
    )

    pool = await init_pool()
    await init_redis()
    lzt = LZTClient()

    logger.info("inventory_cacher_started", refresh_sec=settings.inventory_refresh_sec)
    try:
        while True:
            try:
                await refresh_once(lzt, pool)
            except Exception as exc:
                logger.error("refresh_error", error=str(exc), exc_info=True)
            await asyncio.sleep(settings.inventory_refresh_sec)
    finally:
        await close_redis()
        await close_pool()


if __name__ == "__main__":
    asyncio.run(run())
