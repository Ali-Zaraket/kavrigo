"""Envelope construction and partitioning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from kavrigo_domain import (
    AggressorSide,
    BookTicker,
    InstrumentId,
    MarketTrade,
    Price,
    Quantity,
    SourceKind,
)
from kavrigo_market_ingestion import EVENT_TYPES, envelope_for, partition_key_for

BTC = InstrumentId.parse("BTC-USDT.BINANCE")
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def _trade(**overrides: object) -> MarketTrade:
    values: dict[str, object] = {
        "instrument_id": BTC,
        "price": Price(value=Decimal("61250.10"), base="BTC", quote="USDT"),
        "quantity": Quantity(value=Decimal("0.015"), asset="BTC"),
        "aggressor": AggressorSide.BUY,
        "venue_time": T0,
        "received_at": T0 + timedelta(milliseconds=50),
    }
    values.update(overrides)
    return MarketTrade(**values)  # type: ignore[arg-type]


def _book() -> BookTicker:
    return BookTicker(
        instrument_id=BTC,
        bid_price=Price(value=Decimal("61249.8"), base="BTC", quote="USDT"),
        bid_size=Quantity(value=Decimal("1.2"), asset="BTC"),
        ask_price=Price(value=Decimal("61250.2"), base="BTC", quote="USDT"),
        ask_size=Quantity(value=Decimal("0.9"), asset="BTC"),
        venue_time=None,
        received_at=T0,
        sequence=42,
    )


class TestPartitioning:
    def test_the_key_is_venue_plus_symbol(self) -> None:
        """Ordering is guaranteed only within a partition key (spec 18.3)."""
        assert partition_key_for(_trade()) == "BINANCE:BTC-USDT"

    def test_the_same_instrument_always_lands_on_the_same_partition(self) -> None:
        assert partition_key_for(_trade()) == partition_key_for(_book())

    def test_different_venues_partition_separately(self) -> None:
        other = _trade(
            instrument_id=InstrumentId.parse("BTC-USD.COINBASE"),
            price=Price(value=Decimal("61250"), base="BTC", quote="USD"),
        )
        assert partition_key_for(other) != partition_key_for(_trade())


class TestEnvelope:
    def test_event_time_prefers_the_venue_timestamp(self) -> None:
        envelope = envelope_for(_trade(), provider="binance", ingested_at=T0 + timedelta(seconds=1))
        assert envelope.event_time == T0
        assert envelope.event_type == "market.trade.raw.v1"

    def test_event_time_falls_back_to_arrival_when_the_stream_has_none(self) -> None:
        """Binance's bookTicker carries no venue timestamp."""
        envelope = envelope_for(_book(), provider="binance", ingested_at=T0 + timedelta(seconds=1))
        assert envelope.event_time == T0

    def test_public_market_data_carries_no_tenant_scope(self) -> None:
        assert envelope_for(_trade(), provider="binance", ingested_at=T0).tenant_scope is None

    def test_the_source_records_provenance(self) -> None:
        envelope = envelope_for(
            _trade(),
            provider="binance",
            ingested_at=T0,
            stream="btcusdt@trade",
            sequence=900001,
            license_ref="binance-public-tos",
        )
        assert envelope.source.kind is SourceKind.EXCHANGE_STREAM
        assert envelope.source.venue == "BINANCE"
        assert envelope.source.stream == "btcusdt@trade"
        assert envelope.source.provider_sequence == 900001
        assert envelope.source.license_ref == "binance-public-tos"

    def test_ingest_before_event_time_is_refused(self) -> None:
        """A negative data age would defeat every staleness check downstream."""
        with pytest.raises(ValueError, match="ingested_at precedes event_time"):
            envelope_for(_trade(), provider="binance", ingested_at=T0 - timedelta(seconds=1))

    def test_payload_decimals_survive_as_strings(self) -> None:
        envelope = envelope_for(_trade(), provider="binance", ingested_at=T0)
        assert envelope.payload["price"]["value"] == "61250.10"

    def test_every_event_type_has_a_topic(self) -> None:
        assert set(EVENT_TYPES.values()) == {
            "market.trade.raw.v1",
            "market.book.raw.v1",
            "market.candle.v1",
        }
