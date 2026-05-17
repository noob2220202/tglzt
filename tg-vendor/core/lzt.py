"""Async wrapper around the LOLZTEAM library."""
import asyncio
from decimal import Decimal
from typing import Any

import structlog

from core.cache import cache_get, cache_set
from core.config import settings

logger = structlog.get_logger(__name__)

LZT_BALANCE_CACHE_KEY = "lzt:balance"
LZT_BALANCE_CACHE_TTL = 60


class LZTClient:
    def __init__(self) -> None:
        self._api: Any = None
        self._lock = asyncio.Lock()

    async def _get_api(self) -> Any:
        if self._api is not None:
            return self._api
        async with self._lock:
            if self._api is None:
                from LOLZTEAM import Forum  # type: ignore[import]
                self._api = Forum(token=settings.lzt_token, language="ru")
        return self._api

    async def _call(self, coro_or_func: Any) -> Any:
        """Await if coroutine, else call directly."""
        import inspect
        if inspect.iscoroutine(coro_or_func):
            return await coro_or_func
        if inspect.iscoroutinefunction(coro_or_func):
            return await coro_or_func()
        return coro_or_func

    async def get_telegram_items(self, page: int = 1, **filters: Any) -> list[dict[str, Any]]:
        api = await self._get_api()
        try:
            resp = await self._call(api.market.list(category="telegram", page=page, **filters))
            data = resp.json() if hasattr(resp, "json") else resp
            return data.get("items", []) if isinstance(data, dict) else []
        except Exception as exc:
            logger.error("lzt_list_error", error=str(exc))
            return []

    async def fast_buy(self, item_id: int, price: float) -> dict[str, Any]:
        api = await self._get_api()
        resp = await self._call(api.market.fast_buy(item_id=item_id, price=price))
        data = resp.json() if hasattr(resp, "json") else resp
        return data if isinstance(data, dict) else {}

    async def get_item(self, item_id: int) -> dict[str, Any]:
        api = await self._get_api()
        resp = await self._call(api.market.get_item(item_id=item_id))
        data = resp.json() if hasattr(resp, "json") else resp
        if isinstance(data, dict):
            return data.get("item", data)
        return {}

    async def get_balance(self) -> Decimal:
        cached = cache_get(LZT_BALANCE_CACHE_KEY)
        if cached is not None:
            return Decimal(str(cached))

        api = await self._get_api()
        try:
            resp = await self._call(api.market.get_user_payments())
            data = resp.json() if hasattr(resp, "json") else resp
            if isinstance(data, dict):
                bal = (
                    data.get("user", {}).get("market_balance")
                    or data.get("balance")
                    or 0
                )
                balance = Decimal(str(bal))
            else:
                balance = Decimal("0")
        except Exception as exc:
            logger.error("lzt_balance_error", error=str(exc))
            return Decimal("0")

        cache_set(LZT_BALANCE_CACHE_KEY, str(balance), LZT_BALANCE_CACHE_TTL)
        return balance

    async def request_login_code(self, item_id: int) -> dict[str, Any]:
        api = await self._get_api()
        try:
            resp = await self._call(api.market.telegram_get_login_code(item_id=item_id))
            data = resp.json() if hasattr(resp, "json") else resp
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("login_code_failed", error=str(exc))
            return {}

    async def invalidate_balance_cache(self) -> None:
        from core.cache import cache_delete
        cache_delete(LZT_BALANCE_CACHE_KEY)
