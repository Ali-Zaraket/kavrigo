"""Sink row shaping.

The ClickHouse row format is tested as a pure function so the encoding rules are pinned without
needing a database: decimals as strings, timestamps in the one textual form every ClickHouse
version parses identically, and no value ever routed through a float.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from kavrigo_domain import (
    AggressorSide,
    BookTicker,
    Candle,
    InstrumentId,
    MarketTrade,
    Price,
    Quantity,
)
from kavrigo_market_ingestion import MemorySink, clickhouse_rows_for

BTC = InstrumentId.parse("BTC-USDT.BINANCE")
T0 = datetime(2026, 3, 1, 12, 0, 0, 123000, tzinfo=UTC)
INGESTED = T0 + timedelta(milliseconds=40)


def _trade() -> MarketTrade:
    return MarketTrade(
        instrument_id=BTC,
        price=Price(value=Decimal("61250.10000000"), base="BTC", quote="USDT"),
        quantity=Quantity(value=Decimal("0.01500000"), asset="BTC"),
        aggressor=AggressorSide.BUY,
        venue_trade_id="900001",
        venue_time=T0,
        received_at=INGESTED,
        sequence=900001,
    )


def _book(*, venue_time: datetime | None) -> BookTicker:
    return BookTicker(
        instrument_id=BTC,
        bid_price=Price(value=Decimal("61249.80"), base="BTC", quote="USDT"),
        bid_size=Quantity(value=Decimal("1.245"), asset="BTC"),
        ask_price=Price(value=Decimal("61250.20"), base="BTC", quote="USDT"),
        ask_size=Quantity(value=Decimal("0.873"), asset="BTC"),
        venue_time=venue_time,
        received_at=INGESTED,
        sequence=400900217,
    )


def _candle(*, is_closed: bool) -> Candle:
    return Candle(
        instrument_id=BTC,
        interval="1m",
        open=Decimal("61250.10"),
        high=Decimal("61270.00"),
        low=Decimal("61240.10"),
        close=Decimal("61262.40"),
        volume=Decimal("18.421"),
        quote_volume=Decimal("1128394.20"),
        taker_buy_base_volume=Decimal("9.105"),
        trade_count=450,
        open_time=T0,
        close_time=T0 + timedelta(minutes=1),
        received_at=INGESTED,
        is_closed=is_closed,
    )


class TestEncoding:
    def test_decimals_cross_the_wire_as_strings(self) -> None:
        """A JSON number would be parsed as a double and lose precision on the way in."""
        _table, row = clickhouse_rows_for(_trade(), provider="binance", ingested_at=INGESTED)
        assert row["price"] == "61250.10000000"
        assert isinstance(row["price"], str)
        assert isinstance(row["quantity"], str)

    def test_timestamps_use_the_unambiguous_textual_form(self) -> None:
        """For DateTime64(3) a bare number is interpreted differently across versions."""
        _table, row = clickhouse_rows_for(_trade(), provider="binance", ingested_at=INGESTED)
        assert row["event_time"] == "2026-03-01 12:00:00.123"
        assert row["ingested_at"] == "2026-03-01 12:00:00.163"

    def test_no_float_reaches_a_row(self) -> None:
        for event in (_trade(), _book(venue_time=T0), _candle(is_closed=True)):
            _table, row = clickhouse_rows_for(event, provider="binance", ingested_at=INGESTED)
            floats = [k for k, v in row.items() if isinstance(v, float)]
            assert floats == [], f"{type(event).__name__} row has float fields: {floats}"


class TestRouting:
    @pytest.mark.parametrize(
        ("event", "table"),
        [
            (_trade(), "market_trades"),
            (_book(venue_time=T0), "market_quotes"),
            (_candle(is_closed=True), "market_candles"),
        ],
    )
    def test_events_route_to_their_table(self, event: object, table: str) -> None:
        assert clickhouse_rows_for(event, provider="binance", ingested_at=INGESTED)[0] == table  # type: ignore[arg-type]


class TestQuoteSemantics:
    def test_a_venue_supplied_timestamp_is_flagged(self) -> None:
        _table, row = clickhouse_rows_for(
            _book(venue_time=T0), provider="coinbase", ingested_at=INGESTED
        )
        assert row["has_venue_time"] == 1
        assert row["event_time"] == "2026-03-01 12:00:00.123"

    def test_a_missing_venue_timestamp_is_flagged_and_falls_back_to_arrival(self) -> None:
        """Binance's bookTicker carries none. Without the flag, a consumer could not tell venue
        latency from our own and would understate staleness."""
        _table, row = clickhouse_rows_for(
            _book(venue_time=None), provider="binance", ingested_at=INGESTED
        )
        assert row["has_venue_time"] == 0
        assert row["event_time"] == "2026-03-01 12:00:00.163"

    def test_spread_is_precomputed_in_basis_points(self) -> None:
        _table, row = clickhouse_rows_for(
            _book(venue_time=T0), provider="binance", ingested_at=INGESTED
        )
        assert Decimal(row["spread_bps"]) > 0


class TestCandleSemantics:
    def test_the_closed_flag_is_carried_not_assumed(self) -> None:
        """A backtest that consumes an unclosed bar as final has look-ahead bias (spec 12.3)."""
        _t, closed = clickhouse_rows_for(
            _candle(is_closed=True), provider="binance", ingested_at=INGESTED
        )
        _t2, forming = clickhouse_rows_for(
            _candle(is_closed=False), provider="binance", ingested_at=INGESTED
        )
        assert closed["is_closed"] == 1
        assert forming["is_closed"] == 0

    def test_the_candle_event_time_is_its_close(self) -> None:
        _table, row = clickhouse_rows_for(
            _candle(is_closed=True), provider="binance", ingested_at=INGESTED
        )
        assert row["event_time"] == row["close_time"]


class TestMemorySink:
    async def test_it_records_events_and_batch_sizes(self) -> None:
        sink = MemorySink()
        assert await sink.write([_trade(), _trade()], ingested_at=INGESTED) == 2
        assert await sink.write([], ingested_at=INGESTED) == 0
        assert len(sink.events) == 2
        assert sink.batches == [2, 0]
        await sink.close()
