"""Async wrapper around the LOLZTEAM library for LZT Market interactions."""
import asyncio
from decimal import Decimal
from functools import partial
from typing import Any

import structlog

from core.cache import cache_get, cache_set
from core.config import settings

logger = structlog.get_logger(__name__)

LZT_BALANCE_CACHE_KEY = "lzt:balance"
LZT_BALANCE_CACHE_TTL = 60


class LZTClient:
    """Thread-safe async wrapper. The underlying LOLZTEAM library is synchronous;
    all calls are dispatched to a thread pool executor."""

    def __init__(self) -> None:
        self._api: Any = None
        self._init_lock = asyncio.Lock()

    async def _get_api(self) -> Any:
        if self._api is not None:
            return self._api
        async with self._init_lock:
            if self._api is None:
                self._api = await asyncio.get_event_loop().run_in_executor(
                    None, self._create_api
                )
        return self._api

    @staticmethod
    def _create_api() -> Any:
        try:
            from LOLZTEAM import Forum  # type: ignore[import]
            return Forum(token=settings.lzt_token, language="ru")
        except ImportError:
            raise RuntimeError(
                "LOLZTEAM package not installed. Run: pip install LOLZTEAM"
            )

    async def _call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.get_event_loop().run_in_executor(
            None, partial(func, *args, **kwargs)
        )

    async def get_telegram_items(self, page: int = 1, **filters: Any) -> list[dict[str, Any]]:
        api = await self._get_api()
        try:
            result = await self._call(api.market.list, category="telegram", page=page, **filters)
        except Exception as exc:
            logger.error("lzt_list_error", error=str(exc))
            return []

        if isinstance(result, dict):
            return result.get("items", [])
        return []

    async def fast_buy(self, item_id: int, price: float) -> dict[str, Any]:
        api = await self._get_api()
        result = await self._call(api.market.fast_buy, item_id=item_id, price=price)
        return result if isinstance(result, dict) else {}

    async def get_item(self, item_id: int) -> dict[str, Any]:
        api = await self._get_api()
        result = await self._call(api.market.get_item, item_id=item_id)
        if isinstance(result, dict):
            return result.get("item", result)
        return {}

    async def get_balance(self) -> Decimal:
        cached = await cache_get(LZT_BALANCE_CACHE_KEY)
        if cached is not None:
            try:
                return Decimal(str(cached))
            except Exception:
                pass

        api = await self._get_api()
        try:
            result = await self._call(api.market.get_user_payments)
        except Exception as exc:
            logger.error("lzt_balance_error", error=str(exc))
            return Decimal("0")

        if isinstance(result, dict):
            bal = (
                result.get("user", {}).get("market_balance")
                or result.get("balance")
                or 0
            )
            balance = Decimal(str(bal))
        else:
            balance = Decimal("0")

        await cache_set(LZT_BALANCE_CACHE_KEY, str(balance), LZT_BALANCE_CACHE_TTL)
        return balance

    async def request_login_code(self, item_id: int) -> dict[str, Any]:
        """Request a fresh SMS login code after purchase."""
        api = await self._get_api()
        try:
            result = await self._call(
                api.market.telegram_get_login_code, item_id=item_id
            )
        except Exception as exc:
            # Some LOLZTEAM versions expose it differently
            logger.warning("login_code_primary_failed", error=str(exc))
            try:
                result = await self._call(
                    api.market.get_item, item_id=item_id
                )
            except Exception as exc2:
                logger.error("login_code_fallback_failed", error=str(exc2))
                return {}

        return result if isinstance(result, dict) else {}

    async def invalidate_balance_cache(self) -> None:
        from core.cache import cache_delete
        await cache_delete(LZT_BALANCE_CACHE_KEY)
