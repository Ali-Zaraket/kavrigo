"""Replay tests over recorded venue frames (``MASTER_BUILD_SPEC.md`` §37).

Replaying a recording is how ingestion is tested without a network and how a historical run is
reproduced. These exercise the scenarios that cannot be provoked reliably against a live venue:
reconnect, duplicate delivery, out-of-order frames and sequence gaps.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from kavrigo_domain import AggressorSide, BookTicker, Candle, InstrumentId, MarketTrade
from kavrigo_marketdata import (
    BinanceSpotParser,
    Channel,
    CoinbaseExchangeParser,
    InstrumentMap,
    RecordedFrame,
    ScriptedTransport,
    StreamHealthMonitor,
    StreamKey,
    TransportClosed,
    iter_recorded_frames,
    replay_events,
    write_recording,
)
from kavrigo_marketdata.replay import replayed_market_events

from .conftest import FIXTURES


class TestBinanceRecording:
    def test_the_recording_yields_the_expected_event_mix(
        self, binance_instruments: InstrumentMap
    ) -> None:
        events = list(
            replayed_market_events(
                FIXTURES / "binance_btcusdt.jsonl", BinanceSpotParser(), binance_instruments
            )
        )
        assert sum(isinstance(e, MarketTrade) for e in events) == 3
        assert sum(isinstance(e, BookTicker) for e in events) == 2
        assert sum(isinstance(e, Candle) for e in events) == 1

    def test_the_unsubscribed_symbol_in_the_recording_is_dropped(
        self, binance_instruments: InstrumentMap
    ) -> None:
        """DOGEUSDT appears in the fixture but was never subscribed."""
        events = list(
            replayed_market_events(
                FIXTURES / "binance_btcusdt.jsonl", BinanceSpotParser(), binance_instruments
            )
        )
        assert all(e.instrument_id.base != "DOGE" for e in events)

    def test_the_subscription_acknowledgement_is_classified_as_control(
        self, binance_instruments: InstrumentMap
    ) -> None:
        results = list(
            replay_events(
                FIXTURES / "binance_btcusdt.jsonl", BinanceSpotParser(), binance_instruments
            )
        )
        assert results[0][1].is_control

    def test_aggressor_sides_survive_the_round_trip(
        self, binance_instruments: InstrumentMap
    ) -> None:
        trades = [
            e
            for e in replayed_market_events(
                FIXTURES / "binance_btcusdt.jsonl", BinanceSpotParser(), binance_instruments
            )
            if isinstance(e, MarketTrade) and e.instrument_id.base == "BTC"
        ]
        assert [t.aggressor for t in trades] == [AggressorSide.BUY, AggressorSide.SELL]
        # Cumulative volume delta over the recording.
        assert sum(t.signed_quantity for t in trades) == Decimal("0.01250000")


class TestCoinbaseRecording:
    def test_the_recording_yields_matches_and_a_ticker(
        self, coinbase_instruments: InstrumentMap
    ) -> None:
        events = list(
            replayed_market_events(
                FIXTURES / "coinbase_btcusd.jsonl",
                CoinbaseExchangeParser(),
                coinbase_instruments,
            )
        )
        assert sum(isinstance(e, MarketTrade) for e in events) == 2
        assert sum(isinstance(e, BookTicker) for e in events) == 1

    def test_maker_side_inversion_holds_across_the_recording(
        self, coinbase_instruments: InstrumentMap
    ) -> None:
        trades = [
            e
            for e in replayed_market_events(
                FIXTURES / "coinbase_btcusd.jsonl",
                CoinbaseExchangeParser(),
                coinbase_instruments,
            )
            if isinstance(e, MarketTrade)
        ]
        # Fixture maker sides are sell then buy, so the takers are buy then sell.
        assert [t.aggressor for t in trades] == [AggressorSide.BUY, AggressorSide.SELL]


class TestRecordingFormat:
    def test_a_recording_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "recording.jsonl"
        frames = [
            RecordedFrame(datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC), {"e": "trade", "t": 1}),
            RecordedFrame(datetime(2026, 3, 1, 12, 0, 1, tzinfo=UTC), {"e": "trade", "t": 2}),
        ]
        assert write_recording(path, iter(frames)) == 2
        read_back = list(iter_recorded_frames(path))
        assert [f.frame["t"] for f in read_back] == [1, 2]
        assert read_back[0].received_at == frames[0].received_at

    def test_a_naive_received_at_is_refused(self, tmp_path: Path) -> None:
        """Point-in-time correctness depends on knowing when we knew something (spec 8.5)."""
        path = tmp_path / "bad.jsonl"
        path.write_text('{"received_at":"2026-03-01T12:00:00","frame":{}}\n')
        with pytest.raises(ValueError, match="must carry a UTC offset"):
            list(iter_recorded_frames(path))

    def test_a_malformed_line_fails_loudly(self, tmp_path: Path) -> None:
        """A broken fixture must not let a test pass against half a file."""
        path = tmp_path / "bad.jsonl"
        path.write_text('{"received_at":"2026-03-01T12:00:00+00:00","frame":{}}\nnot json\n')
        with pytest.raises(ValueError, match="malformed recording line"):
            list(iter_recorded_frames(path))

    def test_blank_lines_are_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "spaced.jsonl"
        path.write_text('\n{"received_at":"2026-03-01T12:00:00+00:00","frame":{"x":1}}\n\n')
        assert len(list(iter_recorded_frames(path))) == 1


class TestReplayIntoHealthMonitor:
    """The scenarios MASTER_BUILD_SPEC.md §37 requires replay coverage for."""

    def _key(self) -> StreamKey:
        return StreamKey.of("BINANCE", InstrumentId.parse("BTC-USDT.BINANCE"), Channel.BOOK_TICKER)

    def test_a_gap_in_a_recording_is_detected(self, binance_instruments: InstrumentMap) -> None:
        parser, monitor, key = BinanceSpotParser(), StreamHealthMonitor(), self._key()
        now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
        for update_id in (400900217, 400900218, 400900225):
            parsed = parser.parse(
                {
                    "u": update_id,
                    "s": "BTCUSDT",
                    "b": "61249.80",
                    "B": "1.0",
                    "a": "61250.20",
                    "A": "1.0",
                },
                received_at=now,
                instruments=binance_instruments,
            )
            monitor.observe(key, received_at=now, sequence=parsed.sequence)
        health = monitor.health_for(key)
        assert health.gaps == 1
        assert health.missed_messages == 6

    def test_duplicate_delivery_does_not_double_count(
        self, binance_instruments: InstrumentMap
    ) -> None:
        monitor, key = StreamHealthMonitor(), self._key()
        now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
        for sequence in (1, 2, 2, 3):
            monitor.observe(key, received_at=now, sequence=sequence)
        assert monitor.health_for(key).messages == 3
        assert monitor.health_for(key).duplicates == 1

    def test_out_of_order_frames_do_not_rewind_state(self) -> None:
        monitor, key = StreamHealthMonitor(), self._key()
        now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
        for sequence in (10, 11, 9, 12):
            monitor.observe(key, received_at=now, sequence=sequence)
        assert monitor.health_for(key).last_sequence == 12
        assert monitor.health_for(key).out_of_order == 1


class TestScriptedTransport:
    @staticmethod
    async def _drain(transport: ScriptedTransport) -> list[dict[str, object]]:
        """Collect a session's frames, expecting it to end with TransportClosed."""
        collected: list[dict[str, object]] = []
        # Draining the iterator to exhaustion is the behaviour under test, so the block cannot
        # be reduced to a single statement.
        with pytest.raises(TransportClosed):  # noqa: PT012
            async for frame in transport.frames():
                collected.append(frame)
        return collected

    async def test_a_session_ends_with_transport_closed(self) -> None:
        transport = ScriptedTransport([[{"e": "trade"}]])
        await transport.connect()
        assert await self._drain(transport) == [{"e": "trade"}]

    async def test_a_mid_stream_error_surfaces_to_the_caller(self) -> None:
        transport = ScriptedTransport([[{"ok": 1}, ConnectionResetError("dropped")]])
        await transport.connect()
        with pytest.raises(ConnectionResetError):
            async for _ in transport.frames():
                pass

    async def test_reconnecting_advances_to_the_next_session(self) -> None:
        """The failure shape a real reconnect has: a second session resuming elsewhere."""
        transport = ScriptedTransport([[{"u": 1}], [{"u": 5000}]])
        await transport.connect()
        await self._drain(transport)
        await transport.connect()
        assert transport.connect_count == 2
        assert await self._drain(transport) == [{"u": 5000}]

    async def test_sent_payloads_are_observable(self) -> None:
        transport = ScriptedTransport([[]])
        await transport.connect()
        await transport.send({"method": "SUBSCRIBE", "params": ["btcusdt@trade"]})
        assert transport.sent[0]["params"] == ["btcusdt@trade"]
