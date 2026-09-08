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

#: Anchored to now, deliberately. The market tables carry `TTL event_time + INTERVAL 90 DAY`,
#: so a fixed historical timestamp puts every inserted row past its expiry and ClickHouse
#: deletes it during an ordinary background merge — after the insert reports `written_rows`,
#: and at an unpredictable moment. That produced apparent data loss that looked like a sink bug
#: and reproduced only intermittently. Test data must live inside the retention window.
T0 = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=123000)


@pytest.fixture
async def sink(clickhouse_client: httpx.AsyncClient, provider_tag: str) -> ClickHouseSink:
    """A sink that stamps every row with this test's tag, so its rows are its own."""
    return ClickHouseSink(
        CLICKHOUSE_URL,
        database=CLICKHOUSE_DATABASE,
        user=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        provider=provider_tag,
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


def _bar_time(provider_tag: str) -> datetime:
    """A candle open time unique to this test.

    `market_candles` is a ReplacingMergeTree keyed on (venue, instrument_id, interval,
    open_time) — deliberately, so a bar reissued as it forms collapses into its final version.
    `provider` is not part of that key, so two tests writing a bar at the same open_time are,
    as far as the engine is concerned, the same bar: one silently replaces the other. Giving
    each test its own open_time keeps the production semantics intact while making the rows
    distinct.
    """
    offset = int(provider_tag[-4:], 16) % 5000
    return T0 - timedelta(minutes=offset)


async def _mine(
    client: httpx.AsyncClient, provider_tag: str, table: str, columns: str = "count()"
) -> list[str]:
    """Query only the rows this test wrote.

    Every assertion is scoped by provider tag rather than assuming the table is empty, so a
    concurrent run cannot change the answer.
    """
    return await _query(
        client,
        f"SELECT {columns} FROM {CLICKHOUSE_DATABASE}.{table} WHERE provider = '{provider_tag}'",
    )


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
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient, provider_tag: str
    ) -> None:
        written = await sink.write(
            [_trade(1, "61250.10", "0.015"), _trade(2, "61249.90", "0.0025")],
            ingested_at=T0 + timedelta(milliseconds=50),
        )
        assert written == 2
        assert await _mine(clickhouse_client, provider_tag, "market_trades") == ["2"]

    async def test_decimal_precision_survives_the_round_trip(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient, provider_tag: str
    ) -> None:
        """The whole point of Decimal(38, 18) and string encoding.

        A value routed through a double would come back as 0.100000000000000006 or similar.
        """
        precise = "0.123456789012345678"
        await sink.write([_trade(3, "61250.10", precise)], ingested_at=T0)
        rows = await _mine(clickhouse_client, provider_tag, "market_trades", "toString(quantity)")
        assert Decimal(rows[0]) == Decimal(precise)

    async def test_timestamps_keep_millisecond_precision(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient, provider_tag: str
    ) -> None:
        await sink.write([_trade(4, "61250.10", "0.01")], ingested_at=T0)
        rows = await _mine(clickhouse_client, provider_tag, "market_trades", "toString(event_time)")
        assert rows[0] == T0.strftime("%Y-%m-%d %H:%M:%S.") + "123"

    async def test_the_aggressor_enum_is_accepted(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient, provider_tag: str
    ) -> None:
        await sink.write([_trade(5, "61250.10", "0.01")], ingested_at=T0)
        assert await _mine(clickhouse_client, provider_tag, "market_trades", "aggressor") == ["buy"]

    async def test_an_empty_batch_writes_nothing(self, sink: ClickHouseSink) -> None:
        assert await sink.write([], ingested_at=T0) == 0


class TestMixedBatches:
    async def test_one_batch_fans_out_to_the_right_tables(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient, provider_tag: str
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
        bar_open = _bar_time(provider_tag)
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
            open_time=bar_open,
            close_time=bar_open + timedelta(minutes=1),
            received_at=T0,
            is_closed=True,
        )
        written = await sink.write([_trade(6, "61250.10", "0.01"), book, candle], ingested_at=T0)
        assert written == 3

        for table in ("market_trades", "market_quotes", "market_candles"):
            assert await _mine(clickhouse_client, provider_tag, table) == ["1"], table

    async def test_a_quote_without_a_venue_timestamp_is_flagged(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient, provider_tag: str
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
        rows = await _mine(clickhouse_client, provider_tag, "market_quotes", "has_venue_time")
        assert rows == ["0"]


class TestCandleDeduplication:
    async def test_a_reissued_bar_collapses_to_its_latest_version(
        self, sink: ClickHouseSink, clickhouse_client: httpx.AsyncClient, provider_tag: str
    ) -> None:
        """A bar is re-sent as it forms and again when it closes.

        ReplacingMergeTree keeps the newest; FINAL forces the merge so the test does not depend
        on background merge timing.
        """
        bar_open = _bar_time(provider_tag)
        base = {
            "instrument_id": BTC,
            "interval": "1m",
            "open": Decimal("61250.10"),
            "high": Decimal("61270.00"),
            "low": Decimal("61240.10"),
            "volume": Decimal("18.421"),
            # Both versions share this key on purpose: that is what makes them the same bar.
            "open_time": bar_open,
            "close_time": bar_open + timedelta(minutes=1),
            "received_at": T0,
        }
        forming = Candle(**base, close=Decimal("61255.00"), is_closed=False)  # type: ignore[arg-type]
        closed = Candle(**base, close=Decimal("61262.40"), is_closed=True)  # type: ignore[arg-type]

        await sink.write([forming], ingested_at=T0)
        await sink.write([closed], ingested_at=T0 + timedelta(seconds=30))

        rows = await _mine(
            clickhouse_client, provider_tag, "market_candles FINAL", "toString(close), is_closed"
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
