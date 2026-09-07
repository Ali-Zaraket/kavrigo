"""Pipeline behaviour under the failure modes that actually occur.

``MASTER_BUILD_SPEC.md`` §37 requires replay coverage for reconnect, out-of-order, duplicate
messages, sequence gaps and timeouts. These run entirely against a scripted transport, so they
are deterministic and need no network.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from kavrigo_domain import BookTicker, InstrumentId, MarketTrade
from kavrigo_market_ingestion import IngestionPipeline, MemorySink, PipelineConfig
from kavrigo_marketdata import (
    BinanceSpotParser,
    Channel,
    InstrumentMap,
    ScriptedTransport,
    StreamKey,
    StreamState,
)

BTC = InstrumentId.parse("BTC-USDT.BINANCE")


@pytest.fixture
def instruments() -> InstrumentMap:
    return InstrumentMap({"BTCUSDT": BTC})


def _trade(trade_id: int, *, maker_is_buyer: bool = False) -> dict[str, object]:
    return {
        "e": "trade",
        "E": 1772366400000 + trade_id,
        "s": "BTCUSDT",
        "t": trade_id,
        "p": "61250.10000000",
        "q": "0.01000000",
        "T": 1772366400000 + trade_id,
        "m": maker_is_buyer,
        "M": True,
    }


def _book(update_id: int) -> dict[str, object]:
    return {
        "u": update_id,
        "s": "BTCUSDT",
        "b": "61249.80000000",
        "B": "1.00000000",
        "a": "61250.20000000",
        "A": "1.00000000",
    }


def _pipeline(
    sessions: list[list[object]],
    instruments: InstrumentMap,
    *,
    channels: tuple[Channel, ...] = (Channel.TRADES,),
    max_reconnects: int = 0,
    batch_size: int = 200,
    flush_interval: timedelta = timedelta(seconds=0),
) -> tuple[IngestionPipeline, MemorySink]:
    sink = MemorySink()
    pipeline = IngestionPipeline(
        parser=BinanceSpotParser(),
        transport=ScriptedTransport(sessions),  # type: ignore[arg-type]
        instruments=instruments,
        channels=channels,
        sinks=[sink],
        config=PipelineConfig(
            batch_size=batch_size,
            flush_interval=flush_interval,
            max_reconnects=max_reconnects,
        ),
    )
    return pipeline, sink


class TestHappyPath:
    async def test_frames_become_normalized_events_in_the_sink(
        self, instruments: InstrumentMap
    ) -> None:
        pipeline, sink = _pipeline([[_trade(1), _trade(2), _trade(3)]], instruments)
        stats = await pipeline.run()
        assert stats.events == 3
        assert len(sink.events) == 3
        assert all(isinstance(e, MarketTrade) for e in sink.events)

    async def test_the_subscribe_payload_is_sent_on_connect(
        self, instruments: InstrumentMap
    ) -> None:
        transport = ScriptedTransport([[_trade(1)]])
        sink = MemorySink()
        pipeline = IngestionPipeline(
            parser=BinanceSpotParser(),
            transport=transport,
            instruments=instruments,
            channels=(Channel.TRADES,),
            sinks=[sink],
            config=PipelineConfig(max_reconnects=0),
        )
        await pipeline.run()
        assert transport.sent[0]["method"] == "SUBSCRIBE"
        assert transport.sent[0]["params"] == ["btcusdt@trade"]

    async def test_control_frames_are_counted_separately_from_data(
        self, instruments: InstrumentMap
    ) -> None:
        pipeline, _sink = _pipeline([[{"result": None, "id": 1}, _trade(1)]], instruments)
        stats = await pipeline.run()
        assert stats.control_frames == 1
        assert stats.events == 1


class TestResilience:
    async def test_a_malformed_frame_does_not_stop_the_stream(
        self, instruments: InstrumentMap
    ) -> None:
        """Venues add and malform fields without notice."""
        pipeline, sink = _pipeline(
            [[_trade(1), {"e": "trade", "s": "BTCUSDT", "p": "junk"}, _trade(2)]], instruments
        )
        stats = await pipeline.run()
        assert stats.skipped == 1
        assert stats.events == 2
        assert len(sink.events) == 2

    async def test_an_unsubscribed_symbol_is_skipped(self, instruments: InstrumentMap) -> None:
        frame = _trade(1)
        frame["s"] = "SOLUSDT"
        pipeline, _sink = _pipeline([[frame, _trade(2)]], instruments)
        stats = await pipeline.run()
        assert stats.skipped == 1
        assert stats.events == 1

    async def test_a_dropped_connection_is_reconnected(self, instruments: InstrumentMap) -> None:
        pipeline, sink = _pipeline(
            [[_trade(1), ConnectionResetError("dropped")], [_trade(2)]],
            instruments,
            max_reconnects=1,
        )
        stats = await pipeline.run()
        assert stats.reconnects == 2  # one after the drop, one after the final session ends
        assert [e.venue_trade_id for e in sink.events] == ["1", "2"]

    async def test_events_buffered_before_a_disconnect_are_still_flushed(
        self, instruments: InstrumentMap
    ) -> None:
        """Losing a buffer on disconnect would silently drop observed market data."""
        pipeline, sink = _pipeline(
            [[_trade(1), ConnectionResetError("dropped")]],
            instruments,
            batch_size=1000,
        )
        await pipeline.run()
        assert len(sink.events) == 1

    async def test_an_unexpected_exception_is_not_swallowed(
        self, instruments: InstrumentMap
    ) -> None:
        """Only recoverable network errors are caught; a bug must surface."""
        pipeline, _sink = _pipeline([[ValueError("a real bug")]], instruments)
        with pytest.raises(ValueError, match="a real bug"):
            await pipeline.run()


class TestSequenceHandling:
    async def test_duplicate_frames_are_dropped_before_the_sink(
        self, instruments: InstrumentMap
    ) -> None:
        """At-least-once delivery must not become double-counted volume."""
        pipeline, sink = _pipeline(
            [[_book(10), _book(11), _book(11), _book(12)]],
            instruments,
            channels=(Channel.BOOK_TICKER,),
        )
        stats = await pipeline.run()
        assert stats.dropped_duplicate_or_reordered == 1
        assert len(sink.events) == 3
        assert all(isinstance(e, BookTicker) for e in sink.events)

    async def test_out_of_order_frames_are_dropped(self, instruments: InstrumentMap) -> None:
        pipeline, sink = _pipeline(
            [[_book(10), _book(11), _book(9), _book(12)]],
            instruments,
            channels=(Channel.BOOK_TICKER,),
        )
        stats = await pipeline.run()
        assert stats.dropped_duplicate_or_reordered == 1
        assert [e.sequence for e in sink.events] == [10, 11, 12]

    async def test_a_gap_is_recorded_but_the_message_is_kept(
        self, instruments: InstrumentMap
    ) -> None:
        """The message is valid; dropping it would compound the loss."""
        pipeline, sink = _pipeline(
            [[_book(10), _book(15)]], instruments, channels=(Channel.BOOK_TICKER,)
        )
        await pipeline.run()
        key = StreamKey.of("BINANCE", BTC, Channel.BOOK_TICKER)
        assert pipeline.monitor.health_for(key).gaps == 1
        assert pipeline.monitor.health_for(key).missed_messages == 4
        assert len(sink.events) == 2


class TestHealthIntegration:
    async def test_health_is_tracked_per_stream(self, instruments: InstrumentMap) -> None:
        pipeline, _sink = _pipeline([[_trade(1), _trade(2)]], instruments)
        await pipeline.run()
        key = StreamKey.of("BINANCE", BTC, Channel.TRADES)
        assert pipeline.monitor.health_for(key).messages == 2

    async def test_a_stream_is_marked_reconnecting_after_a_drop(
        self, instruments: InstrumentMap
    ) -> None:
        from datetime import UTC, datetime

        pipeline, _sink = _pipeline([[_trade(1)]], instruments)
        await pipeline.run()
        key = StreamKey.of("BINANCE", BTC, Channel.TRADES)
        state = pipeline.monitor.state_for(key, datetime.now(UTC))
        assert state is StreamState.RECONNECTING
        assert not state.is_usable_for_decisions

    async def test_the_snapshot_is_serialisable_for_metrics(
        self, instruments: InstrumentMap
    ) -> None:
        from datetime import UTC, datetime

        pipeline, _sink = _pipeline([[_trade(1)]], instruments)
        await pipeline.run()
        snapshot = pipeline.monitor.snapshot(datetime.now(UTC))
        assert "BINANCE:BTC-USDT.BINANCE:trades" in snapshot


class TestBatching:
    async def test_a_full_batch_flushes_immediately(self, instruments: InstrumentMap) -> None:
        pipeline, sink = _pipeline(
            [[_trade(i) for i in range(1, 6)]],
            instruments,
            batch_size=2,
            flush_interval=timedelta(hours=1),
        )
        await pipeline.run()
        assert sink.batches[0] == 2
        assert sum(sink.batches) == 5

    async def test_a_quiet_stream_still_flushes_on_the_interval(
        self, instruments: InstrumentMap
    ) -> None:
        """Without a time-based flush, a low-volume market's events would sit in the buffer
        until the batch filled — arriving arbitrarily stale."""
        pipeline, sink = _pipeline(
            [[_trade(1), _trade(2)]],
            instruments,
            batch_size=1000,
            flush_interval=timedelta(seconds=0),
        )
        await pipeline.run()
        assert sink.batches == [1, 1]

    async def test_everything_buffered_is_flushed_when_the_stream_ends(
        self, instruments: InstrumentMap
    ) -> None:
        pipeline, sink = _pipeline(
            [[_trade(i) for i in range(1, 4)]],
            instruments,
            batch_size=1000,
            flush_interval=timedelta(hours=1),
        )
        await pipeline.run()
        assert sum(sink.batches) == 3
