"""Stream health: freshness, sequence continuity and connection stability.

``AGENTS.md`` step 5 requires detecting freshness and sequence gaps, and domain rule 5 makes
data freshness part of risk. This module is where "is the data trustworthy right now?" is
answered, and it answers conservatively: a stream with no recent message is ``STALE``, and one
that has never produced a message is ``UNKNOWN`` rather than healthy.

That default matters. If an unstarted or silent stream reported healthy, the risk engine would
approve trades against data that does not exist (``MASTER_BUILD_SPEC.md`` §11.1, §26.2).

Sequence handling distinguishes three different upstream failures, because they call for
different responses:

* **gap** — messages were lost; the affected state may be wrong and needs a resync;
* **duplicate** — at-least-once redelivery; safe to drop;
* **out-of-order** — frames arrived reordered; the older frame must not overwrite newer state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from kavrigo_domain import InstrumentId
from kavrigo_marketdata.adapter import Channel

__all__ = [
    "SequenceVerdict",
    "StreamHealth",
    "StreamHealthMonitor",
    "StreamKey",
    "StreamState",
]


class StreamState(StrEnum):
    """What the UI shows beside a source (``MASTER_BUILD_SPEC.md`` §31)."""

    LIVE = "live"
    DELAYED = "delayed"
    STALE = "stale"
    RECONNECTING = "reconnecting"
    UNKNOWN = "unknown"

    @property
    def is_usable_for_decisions(self) -> bool:
        """Only ``LIVE`` and ``DELAYED`` may support a decision.

        The risk engine still applies its own per-family freshness budget on top; this is the
        coarse gate, not the whole check.
        """
        return self in {StreamState.LIVE, StreamState.DELAYED}


class SequenceVerdict(StrEnum):
    OK = "ok"
    FIRST = "first"
    GAP = "gap"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    NOT_SEQUENCED = "not_sequenced"

    @property
    def should_process(self) -> bool:
        """Whether the frame should be applied to state.

        A gap is processed — the message itself is valid, and dropping it would compound the
        loss — but it is recorded so a resync can be triggered. Duplicates and out-of-order
        frames are not: applying them would overwrite newer state with older.
        """
        return self in {
            SequenceVerdict.OK,
            SequenceVerdict.FIRST,
            SequenceVerdict.GAP,
            SequenceVerdict.NOT_SEQUENCED,
        }


@dataclass(frozen=True, slots=True)
class StreamKey:
    """Identifies one venue/instrument/channel stream."""

    venue: str
    instrument_id: str
    channel: Channel

    @classmethod
    def of(cls, venue: str, instrument: InstrumentId, channel: Channel) -> StreamKey:
        return cls(venue=venue, instrument_id=instrument.value, channel=channel)


@dataclass(slots=True)
class StreamHealth:
    """Rolling health for one stream."""

    key: StreamKey
    messages: int = 0
    last_message_at: datetime | None = None
    last_venue_time: datetime | None = None
    last_sequence: int | None = None
    gaps: int = 0
    missed_messages: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    parse_failures: int = 0
    reconnects: int = 0
    reconnecting: bool = False
    max_observed_lag_ms: int = 0
    recent_reasons: list[str] = field(default_factory=list)

    def state(
        self, now: datetime, *, delayed_after: timedelta, stale_after: timedelta
    ) -> StreamState:
        if self.reconnecting:
            return StreamState.RECONNECTING
        if self.last_message_at is None:
            # Never produced a message. Not healthy, and explicitly not "live".
            return StreamState.UNKNOWN
        idle = now - self.last_message_at
        if idle >= stale_after:
            return StreamState.STALE
        if idle >= delayed_after:
            return StreamState.DELAYED
        return StreamState.LIVE

    def age_ms(self, now: datetime) -> int | None:
        """Age of the newest data, measured from the venue's own timestamp when it gave one.

        Falls back to arrival time for streams that carry no venue timestamp — Binance's
        ``bookTicker``, for instance. Reporting the arrival time as if it were the venue time
        would understate staleness.
        """
        reference = self.last_venue_time or self.last_message_at
        if reference is None:
            return None
        return max(0, int((now - reference).total_seconds() * 1000))


class StreamHealthMonitor:
    """Tracks every stream an ingestion process is consuming."""

    def __init__(
        self,
        *,
        delayed_after: timedelta = timedelta(seconds=5),
        stale_after: timedelta = timedelta(seconds=30),
        max_recent_reasons: int = 10,
    ) -> None:
        self._streams: dict[StreamKey, StreamHealth] = {}
        self._delayed_after = delayed_after
        self._stale_after = stale_after
        self._max_recent_reasons = max_recent_reasons

    def health_for(self, key: StreamKey) -> StreamHealth:
        return self._streams.setdefault(key, StreamHealth(key=key))

    @property
    def streams(self) -> list[StreamHealth]:
        return list(self._streams.values())

    def observe(
        self,
        key: StreamKey,
        *,
        received_at: datetime,
        venue_time: datetime | None = None,
        sequence: int | None = None,
    ) -> SequenceVerdict:
        """Record one successfully parsed message and classify its sequence."""
        health = self.health_for(key)
        verdict = self._classify(health, sequence)

        if not verdict.should_process:
            return verdict

        health.messages += 1
        health.reconnecting = False
        health.last_message_at = received_at
        if venue_time is not None:
            health.last_venue_time = venue_time
            lag_ms = max(0, int((received_at - venue_time).total_seconds() * 1000))
            health.max_observed_lag_ms = max(health.max_observed_lag_ms, lag_ms)
        if sequence is not None:
            health.last_sequence = sequence
        return verdict

    def _classify(self, health: StreamHealth, sequence: int | None) -> SequenceVerdict:
        if sequence is None:
            return SequenceVerdict.NOT_SEQUENCED
        previous = health.last_sequence
        if previous is None:
            return SequenceVerdict.FIRST
        if sequence == previous + 1:
            return SequenceVerdict.OK
        if sequence == previous:
            health.duplicates += 1
            return SequenceVerdict.DUPLICATE
        if sequence < previous:
            health.out_of_order += 1
            return SequenceVerdict.OUT_OF_ORDER
        health.gaps += 1
        health.missed_messages += sequence - previous - 1
        return SequenceVerdict.GAP

    def record_parse_failure(self, key: StreamKey, reason: str) -> None:
        health = self.health_for(key)
        health.parse_failures += 1
        health.recent_reasons.append(reason)
        del health.recent_reasons[: -self._max_recent_reasons]

    def record_reconnect(self, key: StreamKey) -> None:
        health = self.health_for(key)
        health.reconnects += 1
        health.reconnecting = True
        # The sequence baseline is dropped: after a reconnect the venue may resume from a
        # different point, and comparing against the pre-disconnect value would report a
        # spurious gap of unbounded size.
        health.last_sequence = None

    def record_connected(self, key: StreamKey) -> None:
        self.health_for(key).reconnecting = False

    def state_for(self, key: StreamKey, now: datetime) -> StreamState:
        return self.health_for(key).state(
            now, delayed_after=self._delayed_after, stale_after=self._stale_after
        )

    def unhealthy(self, now: datetime) -> list[StreamHealth]:
        """Streams that must not support a decision right now."""
        return [
            health
            for health in self._streams.values()
            if not health.state(
                now, delayed_after=self._delayed_after, stale_after=self._stale_after
            ).is_usable_for_decisions
        ]

    def snapshot(self, now: datetime) -> dict[str, dict[str, object]]:
        """Serialisable health view for metrics, ``/readyz`` and the UI freshness badges."""
        return {
            f"{h.key.venue}:{h.key.instrument_id}:{h.key.channel.value}": {
                "state": self.state_for(h.key, now).value,
                "age_ms": h.age_ms(now),
                "messages": h.messages,
                "gaps": h.gaps,
                "missed_messages": h.missed_messages,
                "duplicates": h.duplicates,
                "out_of_order": h.out_of_order,
                "parse_failures": h.parse_failures,
                "reconnects": h.reconnects,
                "max_observed_lag_ms": h.max_observed_lag_ms,
            }
            for h in self._streams.values()
        }
