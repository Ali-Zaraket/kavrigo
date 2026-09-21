"""Testnet collection is bounded, mapped, and fails closed on incomplete observations."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kavrigo_domain import BookTicker, InstrumentId, Price, Quantity
from kavrigo_market_ingestion import testnet
from kavrigo_market_ingestion.testnet import (
    TestnetSampleUnavailable as SampleUnavailable,
)
from kavrigo_market_ingestion.testnet import collect_testnet_sample


class FakeTransport:
    def __init__(self, url: str) -> None:
        self.url = url


class FakePipeline:
    complete = True
    overflow = False

    def __init__(self, **kwargs: object) -> None:
        self.sink = kwargs["sinks"][0]  # type: ignore[index]

    async def run(self) -> None:
        now = datetime.now(UTC)
        instruments = [InstrumentId.parse("BTC-USDT.BINANCE_TESTNET")]
        if self.complete:
            instruments.append(InstrumentId.parse("ETH-USDT.BINANCE_TESTNET"))
        events = [
            BookTicker(
                instrument_id=instrument,
                bid_price=Price(value=Decimal("99"), base=instrument.base, quote="USDT"),
                bid_size=Quantity(value=Decimal("1"), asset=instrument.base),
                ask_price=Price(value=Decimal("101"), base=instrument.base, quote="USDT"),
                ask_size=Quantity(value=Decimal("1"), asset=instrument.base),
                received_at=now,
            )
            for instrument in instruments
        ]
        if self.overflow:
            events = events * 5_001
        await self.sink.write(events, ingested_at=now)

    async def aclose(self) -> None:
        return None


async def test_collect_testnet_sample_returns_requested_mapped_books(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakePipeline.complete = True
    FakePipeline.overflow = False
    monkeypatch.setattr(testnet, "PublicWebSocketTransport", FakeTransport)
    monkeypatch.setattr(testnet, "IngestionPipeline", FakePipeline)

    events = await collect_testnet_sample(("BTC", "ETH"), duration_seconds=1)

    assert {event.instrument_id.value for event in events} == {
        "BTC-USDT.BINANCE_TESTNET",
        "ETH-USDT.BINANCE_TESTNET",
    }


async def test_collect_testnet_sample_fails_closed_when_an_asset_has_no_book(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakePipeline.complete = False
    FakePipeline.overflow = False
    monkeypatch.setattr(testnet, "PublicWebSocketTransport", FakeTransport)
    monkeypatch.setattr(testnet, "IngestionPipeline", FakePipeline)

    with pytest.raises(SampleUnavailable, match="missing_book"):
        await collect_testnet_sample(("BTC", "ETH"), duration_seconds=1)


async def test_collect_testnet_sample_fails_closed_at_memory_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakePipeline.complete = True
    FakePipeline.overflow = True
    monkeypatch.setattr(testnet, "PublicWebSocketTransport", FakeTransport)
    monkeypatch.setattr(testnet, "IngestionPipeline", FakePipeline)

    with pytest.raises(SampleUnavailable, match="capacity_exhausted"):
        await collect_testnet_sample(("BTC",), duration_seconds=1)
