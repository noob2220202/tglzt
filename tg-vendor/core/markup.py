import math
from decimal import Decimal

from core.config import settings


def calc_sell_price(lzt_price_usd: Decimal) -> Decimal:
    """Apply markup and round up to 2 decimal places."""
    raw = lzt_price_usd * (Decimal("1") + settings.markup_pct)
    # ceil to 2 decimal places
    return Decimal(math.ceil(float(raw) * 100)) / Decimal("100")
