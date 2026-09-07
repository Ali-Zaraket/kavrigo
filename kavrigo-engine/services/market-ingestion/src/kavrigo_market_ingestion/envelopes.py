"""Wrap normalized events in the canonical envelope (``MASTER_BUILD_SPEC.md`` §18.1).

The envelope is what makes an event self-describing on the bus: where it came from, when it
happened, when we saw it, and which partition key orders it. Ordering is guaranteed only within
a partition key (§18.3), so choosing that key is a correctness decision, not a performance one —
trades for one instrument on one venue must stay in order relative to each other, and nothing
else needs a global order.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from kavrigo_domain import (
    BookTicker,
    Candle,
    EventEnvelope,
    EventSource,
    MarketTrade,
    SourceKind,
)
from kavrigo_marketdata import MarketEvent

__all__ = ["EVENT_TYPES", "envelope_for", "partition_key_for"]

EVENT_TYPES: dict[type, str] = {
    MarketTrade: "market.trade.raw.v1",
    BookTicker: "market.book.raw.v1",
    Candle: "market.candle.v1",
}


def partition_key_for(event: MarketEvent) -> str:
    """``venue + symbol``, per ``MASTER_BUILD_SPEC.md`` §18.3.

    Every event for one instrument on one venue lands on one partition and therefore stays
    ordered relative to its siblings. Using a coarser key (venue alone) would serialise
    unrelated instruments; a finer one would lose the ordering that sequence-gap detection and
    order-flow features depend on.
    """
    return f"{event.instrument_id.venue}:{event.instrument_id.base}-{event.instrument_id.quote}"


def envelope_for(
    event: MarketEvent,
    *,
    provider: str,
    ingested_at: datetime,
    stream: str | None = None,
    sequence: int | None = None,
    trace_id: str | None = None,
    license_ref: str | None = None,
) -> EventEnvelope:
    """Build the envelope for one normalized market event.

    ``event_time`` prefers the venue's own timestamp and falls back to arrival time for streams
    that carry none — Binance's ``bookTicker``, for instance. The fallback is explicit rather
    than silent because ``event_time`` drives every downstream staleness check, and a stream
    whose event time is really an arrival time understates its own lag.
    """
    event_type = EVENT_TYPES.get(type(event))
    if event_type is None:  # pragma: no cover - guarded by the type union
        raise TypeError(f"no event type registered for {type(event).__name__}")

    venue_time = getattr(event, "venue_time", None)
    event_time = venue_time or event.received_at

    return EventEnvelope(
        event_id=f"evt_{uuid.uuid4().hex}",
        event_type=event_type,
        source=EventSource(
            kind=SourceKind.EXCHANGE_STREAM,
            provider=provider,
            venue=event.instrument_id.venue,
            stream=stream,
            schema_version="1",
            provider_sequence=sequence,
            license_ref=license_ref,
        ),
        event_time=event_time,
        ingested_at=ingested_at,
        sequence=sequence,
        partition_key=partition_key_for(event),
        trace_id=trace_id,
        # Public market data is not tenant-scoped: no TenantScope (spec 18.1).
        payload=event.model_dump(mode="json"),
    )
