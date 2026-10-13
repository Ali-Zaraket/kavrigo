"""Strict parsing for an ephemeral local CoinGecko Demo price preview.

Only the documented `/simple/price` fields are accepted. Neither this module nor its caller
stores provider responses or constructs a market snapshot for an agent or paper broker.
Docs verified 2026-10-13: https://docs.coingecko.com/demo/reference/simple-price
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from kavrigo_api.schemas.market_preview import DemoMarketPreview, DemoReferencePrice


class DemoPriceError(ValueError):
    """The provider did not return usable reference prices."""


_URL = "https://api.coingecko.com/api/v3/simple/price"
_PARAMS = {
    "ids": "bitcoin,ethereum",
    "vs_currencies": "usd",
    "include_last_updated_at": "true",
    "precision": "full",
}


async def fetch_demo_prices(
    client: httpx.AsyncClient, *, api_key: str, fetched_at: datetime
) -> DemoMarketPreview:
    try:
        response = await client.get(_URL, params=_PARAMS, headers={"x-cg-demo-api-key": api_key})
    except httpx.RequestError as exc:
        raise DemoPriceError("provider request failed") from exc
    if response.status_code != 200:
        raise DemoPriceError("provider returned non-success status")
    return parse_demo_prices(response.text, fetched_at=fetched_at)


def parse_demo_prices(payload: str, *, fetched_at: datetime) -> DemoMarketPreview:
    try:
        data: Any = json.loads(payload, parse_float=Decimal)
    except (ValueError, TypeError) as exc:
        raise DemoPriceError("invalid provider response") from exc
    if not isinstance(data, dict):
        raise DemoPriceError("invalid provider response")
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at must be timezone aware")

    prices: list[DemoReferencePrice] = []
    for coin_id, asset in (("bitcoin", "BTC"), ("ethereum", "ETH")):
        coin = data.get(coin_id)
        if not isinstance(coin, dict):
            raise DemoPriceError("missing coin")
        value = coin.get("usd")
        epoch = coin.get("last_updated_at")
        if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
            raise DemoPriceError("invalid price")
        amount = Decimal(value)
        if not amount.is_finite() or amount <= 0:
            raise DemoPriceError("invalid price")
        if isinstance(epoch, bool) or not isinstance(epoch, int):
            raise DemoPriceError("missing observation time")
        try:
            observed_at = datetime.fromtimestamp(epoch, tz=UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise DemoPriceError("invalid observation time") from exc
        if observed_at > fetched_at + timedelta(seconds=30):
            raise DemoPriceError("future observation time")
        prices.append(
            DemoReferencePrice(
                asset=asset,
                amount=amount,
                observed_at=observed_at,
                freshness="fresh" if fetched_at - observed_at <= timedelta(minutes=5) else "stale",
            )
        )

    return DemoMarketPreview(fetched_at=fetched_at, prices=prices)
