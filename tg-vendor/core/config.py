from decimal import Decimal
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str
    admin_tg_ids: List[int] = []
    lzt_token: str
    trongrid_api_key: str
    deposit_address: str
    usdt_contract: str = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    db_url: str
    redis_url: str
    markup_pct: Decimal = Decimal("0.25")
    inventory_refresh_sec: int = 30
    tron_poll_sec: int = 30
    lzt_balance_min_usd: Decimal = Decimal("10")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("admin_tg_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: object) -> List[int]:
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v  # type: ignore[return-value]


settings = Settings()
