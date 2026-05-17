import asyncio
import re
from decimal import Decimal
from typing import Any

import httpx
import structlog

from core.config import settings

logger = structlog.get_logger(__name__)

_ADDRESS_RE = re.compile(r"^T[A-Za-z0-9]{33}$")

USDT_DECIMALS = Decimal("1000000")  # 10^6


def validate_trc20_address(addr: str) -> bool:
    """Validate TRC20 address format and base58 checksum."""
    if not _ADDRESS_RE.match(addr):
        return False
    try:
        import tronpy.keys as tron_keys
        if hasattr(tron_keys, "is_address"):
            return bool(tron_keys.is_address(addr))
        # Fallback: try decoding base58check
        from tronpy.keys import PrivateKey  # noqa: F401 — triggers import of base58 utils
        import base58  # type: ignore[import]
        decoded = base58.b58decode_check(addr)
        return len(decoded) == 21 and decoded[0] == 0x41
    except Exception:
        return False


class TronGridClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://api.trongrid.io",
            headers={"TRON-PRO-API-KEY": settings.trongrid_api_key},
            timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_trc20_transfers(
        self,
        address: str,
        min_timestamp: int,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Fetch TRC20 USDT transfers to address with exponential backoff on 429."""
        params = {
            "only_to": "true",
            "contract_address": settings.usdt_contract,
            "min_timestamp": min_timestamp,
            "limit": limit,
            "order_by": "block_timestamp,asc",
        }
        url = f"/v1/accounts/{address}/transactions/trc20"

        delay = 1.0
        for attempt in range(6):
            try:
                resp = await self._client.get(url, params=params)
                if resp.status_code == 429:
                    wait = min(delay, 60.0)
                    logger.warning("TronGrid 429, backing off", wait=wait)
                    await asyncio.sleep(wait)
                    delay = min(delay * 2, 60.0)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", [])
            except httpx.HTTPStatusError as exc:
                logger.error("TronGrid HTTP error", status=exc.response.status_code)
                raise
            except httpx.RequestError as exc:
                logger.error("TronGrid request error", exc=str(exc))
                if attempt == 5:
                    raise
                await asyncio.sleep(min(delay, 60.0))
                delay = min(delay * 2, 60.0)

        return []
