"""Stream health: freshness states and sequence-continuity classification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kavrigo_domain import InstrumentId
from kavrigo_marketdata import (
    Channel,
    SequenceVerdict,
    StreamHealthMonitor,
    StreamKey,
    StreamState,
)

T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
BTC = InstrumentId.parse("BTC-USDT.BINANCE")


@pytest.fixture
def key() -> StreamKey:
    return StreamKey.of("BINANCE", BTC, Channel.TRADES)


@pytest.fixture
def monitor() -> StreamHealthMonitor:
    return StreamHealthMonitor(
        delayed_after=timedelta(seconds=5), stale_after=timedelta(seconds=30)
    )


class TestFreshnessStates:
    def test_a_stream_that_never_produced_a_message_is_unknown_not_live(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        """The fail-closed default. A silent stream reporting healthy would let the risk
        engine approve trades against data that does not exist."""
        state = monitor.state_for(key, T0)
        assert state is StreamState.UNKNOWN
        assert not state.is_usable_for_decisions

    def test_states_progress_from_live_to_delayed_to_stale(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        monitor.observe(key, received_at=T0, venue_time=T0, sequence=1)
        assert monitor.state_for(key, T0 + timedelta(seconds=1)) is StreamState.LIVE
        assert monitor.state_for(key, T0 + timedelta(seconds=10)) is StreamState.DELAYED
        assert monitor.state_for(key, T0 + timedelta(seconds=60)) is StreamState.STALE

    def test_only_live_and_delayed_may_support_a_decision(self) -> None:
        assert StreamState.LIVE.is_usable_for_decisions
        assert StreamState.DELAYED.is_usable_for_decisions
        for state in (StreamState.STALE, StreamState.RECONNECTING, StreamState.UNKNOWN):
            assert not state.is_usable_for_decisions

    def test_age_is_measured_from_the_venue_timestamp_when_there_is_one(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        """Measuring from arrival time instead would hide venue-side lag."""
        monitor.observe(key, received_at=T0 + timedelta(seconds=2), venue_time=T0, sequence=1)
        assert monitor.health_for(key).age_ms(T0 + timedelta(seconds=3)) == 3000

    def test_age_falls_back_to_arrival_when_the_stream_has_no_venue_time(
        self, monitor: StreamHealthMonitor
    ) -> None:
        book = StreamKey.of("BINANCE", BTC, Channel.BOOK_TICKER)
        monitor.observe(book, received_at=T0, venue_time=None, sequence=1)
        assert monitor.health_for(book).age_ms(T0 + timedelta(seconds=4)) == 4000

    def test_unhealthy_lists_streams_that_must_not_support_a_decision(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        monitor.observe(key, received_at=T0, venue_time=T0, sequence=1)
        assert monitor.unhealthy(T0 + timedelta(seconds=1)) == []
        assert [h.key for h in monitor.unhealthy(T0 + timedelta(minutes=5))] == [key]


class TestSequenceContinuity:
    def test_the_first_message_establishes_a_baseline(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        assert monitor.observe(key, received_at=T0, sequence=100) is SequenceVerdict.FIRST

    def test_consecutive_sequences_are_ok(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        monitor.observe(key, received_at=T0, sequence=100)
        assert monitor.observe(key, received_at=T0, sequence=101) is SequenceVerdict.OK
        assert monitor.health_for(key).gaps == 0

    def test_a_gap_is_recorded_with_the_number_of_missed_messages(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        monitor.observe(key, received_at=T0, sequence=100)
        assert monitor.observe(key, received_at=T0, sequence=105) is SequenceVerdict.GAP
        health = monitor.health_for(key)
        assert health.gaps == 1
        assert health.missed_messages == 4

    def test_a_gapped_message_is_still_processed(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        """The message itself is valid; dropping it would compound the loss."""
        assert SequenceVerdict.GAP.should_process

    def test_a_duplicate_is_detected_and_not_processed(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        """At-least-once redelivery is normal; applying it twice is not."""
        monitor.observe(key, received_at=T0, sequence=100)
        monitor.observe(key, received_at=T0, sequence=101)
        assert monitor.observe(key, received_at=T0, sequence=101) is SequenceVerdict.DUPLICATE
        assert monitor.health_for(key).duplicates == 1
        assert monitor.health_for(key).messages == 2
        assert not SequenceVerdict.DUPLICATE.should_process

    def test_an_out_of_order_frame_is_not_applied(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        """Applying it would overwrite newer state with older."""
        monitor.observe(key, received_at=T0, sequence=100)
        monitor.observe(key, received_at=T0, sequence=101)
        assert monitor.observe(key, received_at=T0, sequence=99) is SequenceVerdict.OUT_OF_ORDER
        assert monitor.health_for(key).last_sequence == 101
        assert not SequenceVerdict.OUT_OF_ORDER.should_process

    def test_unsequenced_streams_are_not_penalised(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        for _ in range(3):
            assert (
                monitor.observe(key, received_at=T0, sequence=None) is SequenceVerdict.NOT_SEQUENCED
            )
        assert monitor.health_for(key).gaps == 0
        assert monitor.health_for(key).messages == 3


class TestReconnects:
    def test_reconnecting_is_reported_and_is_not_usable(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        monitor.observe(key, received_at=T0, sequence=1)
        monitor.record_reconnect(key)
        assert monitor.state_for(key, T0) is StreamState.RECONNECTING
        assert not monitor.state_for(key, T0).is_usable_for_decisions

    def test_a_reconnect_clears_the_sequence_baseline(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        """A venue may resume from a different point; comparing across the break would report
        a spurious gap of unbounded size."""
        monitor.observe(key, received_at=T0, sequence=100)
        monitor.record_reconnect(key)
        assert monitor.observe(key, received_at=T0, sequence=900_000) is SequenceVerdict.FIRST
        assert monitor.health_for(key).gaps == 0

    def test_the_first_message_after_a_reconnect_clears_the_flag(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        monitor.record_reconnect(key)
        monitor.observe(key, received_at=T0, sequence=1)
        assert monitor.state_for(key, T0) is StreamState.LIVE
        assert monitor.health_for(key).reconnects == 1


class TestReporting:
    def test_parse_failures_keep_a_bounded_reason_history(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        for i in range(25):
            monitor.record_parse_failure(key, f"reason {i}")
        health = monitor.health_for(key)
        assert health.parse_failures == 25
        assert len(health.recent_reasons) == 10
        assert health.recent_reasons[-1] == "reason 24"

    def test_the_snapshot_exposes_every_metric_the_ui_and_alerts_need(
        self, monitor: StreamHealthMonitor, key: StreamKey
    ) -> None:
        monitor.observe(key, received_at=T0, venue_time=T0, sequence=1)
        snapshot = monitor.snapshot(T0 + timedelta(seconds=1))
        entry = snapshot["BINANCE:BTC-USDT.BINANCE:trades"]
        assert entry["state"] == "live"
        assert entry["age_ms"] == 1000
        assert set(entry) >= {
            "state",
            "age_ms",
            "messages",
            "gaps",
            "missed_messages",
            "duplicates",
            "out_of_order",
            "parse_failures",
            "reconnects",
        }
