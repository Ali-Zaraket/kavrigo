"""Local-only CoinGecko Demo reference prices; never an executable market snapshot."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DemoReferencePrice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    asset: Literal["BTC", "ETH"]
    currency: Literal["USD"] = "USD"
    amount: Decimal
    observed_at: datetime
    freshness: Literal["fresh", "stale"]


class DemoMarketPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["demo"] = "demo"
    use: Literal["research_preview_only"] = "research_preview_only"
    provider: Literal["CoinGecko"] = "CoinGecko"
    attribution: Literal["Data provided by CoinGecko"] = "Data provided by CoinGecko"
    attribution_url: Literal["https://www.coingecko.com/en/api"] = (
        "https://www.coingecko.com/en/api"
    )
    fetched_at: datetime
    prices: list[DemoReferencePrice]
