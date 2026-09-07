"""ClickHouse sink against a real database.

Row shaping is unit-tested; this proves the shapes ClickHouse actually accepts — which is where
decimal precision and DateTime64 parsing either hold or quietly do not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
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
from kavrigo_market_ingestion import ClickHouseSink

from .conftest import CLICKHOUSE_DATABASE, CLICKHOUSE_PASSWORD, CLICKHOUSE_URL, CLICKHOUSE_USER

pytestmark = pytest.mark.integration

BTC = InstrumentId.parse("BTC-USDT.BINANCE")
T0 = datetime(2026, 3, 1, 12, 0, 0, 123000, tzinfo=UTC)


@pytest.fixture
async def sink(clickhouse_client: httpx.AsyncClient) -> ClickHouseSink:
    return ClickHouseSink(
        CLICKHOUSE_URL,
        database=CLICKHOUSE_DATABASE,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        provider="binance",
        client=clickhouse_client,
    )


async def _query(client: httpx.AsyncClient, sql: str) -> list[str]:
    response = await client.post(
        CLICKHOUSE_URL,
        params={"query": sql},
        headers={"X-ClickHouse-User": CLICKHOUSE_USER, "X-ClickHouse-Key": CLICKHOUSE_PASSWORD},
    )
    response.raise_for_status()
    return [line for line in response.text.strip().split("\n") if line]


def _trade(trade_id: int, price: str, quantity: str) -> MarketTrade:
    return MarketTrade(
        instrument_id=BTC,
        price=Price(value=Decimal(price), base="BTC", quote="USDT"),
        quantity=Quantity(value=Decimal(quantity), asset="BTC"),
        aggressor=AggressorSide.BUY,
        venue_trade_id=str(trade_id),
        venue_time=T0,
        received_at=T0 + timedelta(milliseconds=40),
        sequence=trade_id,
    )


class TestTradeInserts:
    async def test_trades_are_written_and_readable(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient
    ) -> None:
        written = await sink.write(
            [_trade(1, "61250.10", "0.015"), _trade(2, "61249.90", "0.0025")],
            ingested_at=T0 + timedelta(milliseconds=50),
        )
        assert written == 2
        rows = await _query(
            clickhouse_client, f"SELECT count() FROM {CLICKHOUSE_DATABASE}.market_trades"
        )
        assert rows == ["2"]

    async def test_decimal_precision_survives_the_round_trip(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient
    ) -> None:
        """The whole point of Decimal(38, 18) and string encoding.

        A value routed through a double would come back as 0.100000000000000006 or similar.
        """
        precise = "0.123456789012345678"
        await sink.write([_trade(3, "61250.10", precise)], ingested_at=T0)
        rows = await _query(
            clickhouse_client,
            f"SELECT toString(quantity) FROM {CLICKHOUSE_DATABASE}.market_trades",
        )
        assert Decimal(rows[0]) == Decimal(precise)

    async def test_timestamps_keep_millisecond_precision(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient
    ) -> None:
        await sink.write([_trade(4, "61250.10", "0.01")], ingested_at=T0)
        rows = await _query(
            clickhouse_client,
            f"SELECT toString(event_time) FROM {CLICKHOUSE_DATABASE}.market_trades",
        )
        assert rows[0].endswith("12:00:00.123")

    async def test_the_aggressor_enum_is_accepted(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient
    ) -> None:
        await sink.write([_trade(5, "61250.10", "0.01")], ingested_at=T0)
        rows = await _query(
            clickhouse_client, f"SELECT aggressor FROM {CLICKHOUSE_DATABASE}.market_trades"
        )
        assert rows == ["buy"]

    async def test_an_empty_batch_writes_nothing(self, sink: ClickHouseSink) -> None:
        assert await sink.write([], ingested_at=T0) == 0


class TestMixedBatches:
    async def test_one_batch_fans_out_to_the_right_tables(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient
    ) -> None:
        book = BookTicker(
            instrument_id=BTC,
            bid_price=Price(value=Decimal("61249.80"), base="BTC", quote="USDT"),
            bid_size=Quantity(value=Decimal("1.245"), asset="BTC"),
            ask_price=Price(value=Decimal("61250.20"), base="BTC", quote="USDT"),
            ask_size=Quantity(value=Decimal("0.873"), asset="BTC"),
            venue_time=None,
            received_at=T0,
            sequence=400900217,
        )
        candle = Candle(
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
            received_at=T0,
            is_closed=True,
        )
        written = await sink.write([_trade(6, "61250.10", "0.01"), book, candle], ingested_at=T0)
        assert written == 3

        for table, expected in (
            ("market_trades", "1"),
            ("market_quotes", "1"),
            ("market_candles", "1"),
        ):
            rows = await _query(
                clickhouse_client, f"SELECT count() FROM {CLICKHOUSE_DATABASE}.{table}"
            )
            assert rows == [expected], table

    async def test_a_quote_without_a_venue_timestamp_is_flagged(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient
    ) -> None:
        book = BookTicker(
            instrument_id=BTC,
            bid_price=Price(value=Decimal("61249.80"), base="BTC", quote="USDT"),
            bid_size=Quantity(value=Decimal("1.0"), asset="BTC"),
            ask_price=Price(value=Decimal("61250.20"), base="BTC", quote="USDT"),
            ask_size=Quantity(value=Decimal("1.0"), asset="BTC"),
            venue_time=None,
            received_at=T0,
            sequence=1,
        )
        await sink.write([book], ingested_at=T0)
        rows = await _query(
            clickhouse_client, f"SELECT has_venue_time FROM {CLICKHOUSE_DATABASE}.market_quotes"
        )
        assert rows == ["0"]


class TestCandleDeduplication:
    async def test_a_reissued_bar_collapses_to_its_latest_version(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient
    ) -> None:
        """A bar is re-sent as it forms and again when it closes.

        ReplacingMergeTree keeps the newest; FINAL forces the merge so the test does not depend
        on background merge timing.
        """
        base = {
            "instrument_id": BTC,
            "interval": "1m",
            "open": Decimal("61250.10"),
            "high": Decimal("61270.00"),
            "low": Decimal("61240.10"),
            "volume": Decimal("18.421"),
            "open_time": T0,
            "close_time": T0 + timedelta(minutes=1),
            "received_at": T0,
        }
        forming = Candle(**base, close=Decimal("61255.00"), is_closed=False)  # type: ignore[arg-type]
        closed = Candle(**base, close=Decimal("61262.40"), is_closed=True)  # type: ignore[arg-type]

        await sink.write([forming], ingested_at=T0)
        await sink.write([closed], ingested_at=T0 + timedelta(seconds=30))

        rows = await _query(
            clickhouse_client,
            f"SELECT toString(close), is_closed FROM {CLICKHOUSE_DATABASE}.market_candles FINAL",
        )
        assert len(rows) == 1
        close, is_closed = rows[0].split("\t")
        assert Decimal(close) == Decimal("61262.40")
        assert is_closed == "1"


class TestFailureReporting:
    async def test_a_schema_mismatch_reports_clickhouses_own_diagnostic(
        self, clickhouse_client: httpx.AsyncClient
    ) -> None:
        """A bare status code would make a schema drift undebuggable."""
        broken = ClickHouseSink(
            CLICKHOUSE_URL,
            database=CLICKHOUSE_DATABASE,
            user=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            provider="binance",
            client=clickhouse_client,
        )
        with pytest.raises(RuntimeError, match="ClickHouse insert into"):
            await broken._insert("no_such_table", [{"a": 1}])

    async def test_ping_reports_reachability(self, sink: ClickHouseSink) -> None:
        assert await sink.ping() is True
