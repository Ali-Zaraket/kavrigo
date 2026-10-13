"""Demo preview must preserve decimals, expose freshness and fail closed."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from kavrigo_api.services.coingecko_demo import (
    DemoPriceError,
    fetch_demo_prices,
    parse_demo_prices,
)

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def payload(*, btc_time: datetime = NOW, eth_time: datetime = NOW) -> str:
    return json.dumps(
        {
            "bitcoin": {"usd": 78912.12345678, "last_updated_at": int(btc_time.timestamp())},
            "ethereum": {"usd": 3100.25, "last_updated_at": int(eth_time.timestamp())},
        }
    )


def test_parse_marks_freshness_and_keeps_reference_data_out_of_trading() -> None:
    result = parse_demo_prices(payload(eth_time=NOW - timedelta(minutes=6)), fetched_at=NOW)
    assert result.mode == "demo"
    assert result.use == "research_preview_only"
    assert [p.freshness for p in result.prices] == ["fresh", "stale"]
    assert result.prices[0].amount.as_tuple().exponent == -8
    assert result.attribution_url == "https://www.coingecko.com/en/api"


@pytest.mark.parametrize(
    "body",
    [
        "not JSON",
        "[]",
        '{"bitcoin":{"usd":1,"last_updated_at":1}}',
        '{"bitcoin":{"usd":-1,"last_updated_at":1},"ethereum":{"usd":1,"last_updated_at":1}}',
        '{"bitcoin":{"usd":true,"last_updated_at":1},"ethereum":{"usd":1,"last_updated_at":1}}',
        '{"bitcoin":{"usd":1,"last_updated_at":true},"ethereum":{"usd":1,"last_updated_at":1}}',
    ],
)
def test_malformed_provider_response_is_rejected(body: str) -> None:
    with pytest.raises(DemoPriceError):
        parse_demo_prices(body, fetched_at=NOW)


def test_future_provider_timestamp_is_rejected() -> None:
    with pytest.raises(DemoPriceError, match="future"):
        parse_demo_prices(payload(btc_time=NOW + timedelta(minutes=1)), fetched_at=NOW)


@pytest.mark.asyncio
async def test_fetch_uses_demo_header_and_fixed_batched_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.coingecko.com"
        assert request.url.path == "/api/v3/simple/price"
        assert request.url.params["ids"] == "bitcoin,ethereum"
        assert request.url.params["include_last_updated_at"] == "true"
        assert request.headers["x-cg-demo-api-key"] == "test-key"
        assert "test-key" not in str(request.url)
        return httpx.Response(200, text=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_demo_prices(client, api_key="test-key", fetched_at=NOW)
    assert len(result.prices) == 2


@pytest.mark.asyncio
async def test_fetch_rejects_upstream_failure_without_returning_body() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, text="secret body"))
    ) as client:
        with pytest.raises(DemoPriceError) as exc:
            await fetch_demo_prices(client, api_key="test-key", fetched_at=NOW)
    assert "secret body" not in str(exc.value)
