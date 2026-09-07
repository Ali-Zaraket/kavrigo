"""The ingestion pipeline: venue frames in, normalized events out.

```text
transport → parser → health monitor → batch → sinks
```

Responsibilities kept deliberately narrow, because this loop runs unattended for days:

* **Never die on bad input.** A parse failure is counted and skipped. Venues change fields
  without notice, and one unexpected frame must not stop a stream.
* **Reconnect with backoff and jitter.** A venue that drops every consumer at once must not get
  them all back in lockstep.
* **Drop what should not be applied.** Duplicates and out-of-order frames are counted and
  discarded before reaching a sink, so at-least-once delivery does not become double-counted
  volume.
* **Never touch credentials.** Public streams only.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

from kavrigo_market_ingestion.sinks import EventSink
from kavrigo_marketdata import (
    Channel,
    InstrumentMap,
    MarketEvent,
    StreamHealthMonitor,
    StreamKey,
    Transport,
    TransportClosed,
    VenueParser,
    backoff_delays,
)

__all__ = ["IngestionPipeline", "IngestionStats", "PipelineConfig"]

_log = structlog.get_logger("kavrigo.ingestion")

_CHANNEL_FOR_EVENT = {
    "MarketTrade": Channel.TRADES,
    "BookTicker": Channel.BOOK_TICKER,
    "Candle": Channel.CANDLES,
}


@dataclass(slots=True)
class PipelineConfig:
    batch_size: int = 200
    flush_interval: timedelta = timedelta(seconds=1)
    interval: str = "1m"
    max_reconnects: int | None = None
    """``None`` means reconnect forever. Tests bound it so they terminate."""


@dataclass(slots=True)
class IngestionStats:
    frames: int = 0
    events: int = 0
    control_frames: int = 0
    skipped: int = 0
    dropped_duplicate_or_reordered: int = 0
    written: int = 0
    reconnects: int = 0


class IngestionPipeline:
    """Consumes one venue connection and writes normalized events to sinks."""

    def __init__(
        self,
        *,
        parser: VenueParser,
        transport: Transport,
        instruments: InstrumentMap,
        channels: Sequence[Channel],
        sinks: Sequence[EventSink],
        monitor: StreamHealthMonitor | None = None,
        config: PipelineConfig | None = None,
    ) -> None:
        self._parser = parser
        self._transport = transport
        self._instruments = instruments
        self._channels = tuple(channels)
        self._sinks = list(sinks)
        self.monitor = monitor or StreamHealthMonitor()
        self._config = config or PipelineConfig()
        self.stats = IngestionStats()
        self._buffer: list[MarketEvent] = []
        self._last_flush = datetime.now(UTC)

    async def run(self) -> IngestionStats:
        """Connect, consume and reconnect until the reconnect budget is exhausted."""
        delays = backoff_delays()
        attempt = 0
        while True:
            try:
                await self._transport.connect()
                for payload in self._parser.subscribe_payloads(
                    self._instruments, self._channels, interval=self._config.interval
                ):
                    await self._transport.send(payload)
                await self._consume()
            except TransportClosed:
                _log.info("stream_closed", venue=self._parser.venue)
            except (TimeoutError, ConnectionError, OSError) as exc:
                # Expected, recoverable network failures. Anything else propagates: an
                # unexpected exception is a bug, and swallowing it would hide it forever.
                _log.warning(
                    "stream_error", venue=self._parser.venue, error_type=type(exc).__name__
                )
            finally:
                await self._flush()

            self._mark_reconnecting()
            attempt += 1
            self.stats.reconnects += 1
            if self._config.max_reconnects is not None and attempt > self._config.max_reconnects:
                return self.stats
            await asyncio.sleep(await anext(delays))

    async def _consume(self) -> None:
        async for frame in self._transport.frames():
            received_at = datetime.now(UTC)
            self.stats.frames += 1
            parsed = self._parser.parse(
                frame, received_at=received_at, instruments=self._instruments
            )

            if parsed.is_control:
                self.stats.control_frames += 1
                continue

            event = parsed.event
            if event is None:
                self.stats.skipped += 1
                _log.debug(
                    "frame_skipped", venue=self._parser.venue, reason=parsed.reason or "unknown"
                )
                continue

            key = StreamKey.of(
                self._parser.venue,
                event.instrument_id,
                _CHANNEL_FOR_EVENT[type(event).__name__],
            )
            verdict = self.monitor.observe(
                key,
                received_at=received_at,
                venue_time=getattr(event, "venue_time", None),
                sequence=parsed.sequence,
            )
            if not verdict.should_process:
                self.stats.dropped_duplicate_or_reordered += 1
                continue

            self.stats.events += 1
            self._buffer.append(event)
            if self._should_flush(received_at):
                await self._flush()

    def _should_flush(self, now: datetime) -> bool:
        if len(self._buffer) >= self._config.batch_size:
            return True
        # A time-based flush matters for quiet instruments: without it, a low-volume market's
        # events would sit in the buffer until the batch filled, arriving arbitrarily stale.
        return bool(self._buffer) and now - self._last_flush >= self._config.flush_interval

    async def _flush(self) -> None:
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        ingested_at = datetime.now(UTC)
        for sink in self._sinks:
            written = await sink.write(batch, ingested_at=ingested_at)
            self.stats.written += written
        self._last_flush = ingested_at

    def _mark_reconnecting(self) -> None:
        for instrument in self._instruments.instruments:
            for channel in self._channels:
                self.monitor.record_reconnect(StreamKey.of(self._parser.venue, instrument, channel))

    async def aclose(self) -> None:
        await self._flush()
        with contextlib.suppress(Exception):
            await self._transport.close()
        for sink in self._sinks:
            await sink.close()
