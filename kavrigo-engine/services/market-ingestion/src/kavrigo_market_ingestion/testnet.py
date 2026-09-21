"""Bounded Binance Spot Testnet collection for local, execution-disabled rehearsals."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta

from kavrigo_domain import BookTicker, MarketTrade
from kavrigo_market_ingestion.pipeline import IngestionPipeline, PipelineConfig
from kavrigo_market_ingestion.settings import testnet_venues
from kavrigo_marketdata import InstrumentMap, MarketEvent, PublicWebSocketTransport

__all__ = ["TestnetSampleUnavailable", "collect_testnet_sample"]


class TestnetSampleUnavailable(RuntimeError):
    """The bounded sample did not contain enough data for every requested asset."""


class _BoundedSampleSink:
    """Retain a small sample and fail rather than grow memory on an abnormal stream."""

    def __init__(self, max_events: int = 5_000) -> None:
        self.events: list[MarketEvent] = []
        self._max_events = max_events

    async def write(self, events: Sequence[MarketEvent], *, ingested_at: datetime) -> int:
        if len(self.events) + len(events) > self._max_events:
            raise TestnetSampleUnavailable("testnet_sample_capacity_exhausted")
        self.events.extend(events)
        return len(events)

    async def close(self) -> None:
        return None


async def collect_testnet_sample(
    bases: tuple[str, ...], *, duration_seconds: int = 10
) -> tuple[MarketTrade | BookTicker, ...]:
    """Collect simulated BTC/ETH events in memory and return no transport/provider objects."""
    if not bases or len(bases) > 2 or any(base not in {"BTC", "ETH"} for base in bases):
        raise ValueError("testnet_sample_supports_btc_and_eth_only")
    if not 1 <= duration_seconds <= 15:
        raise ValueError("testnet_sample_duration_out_of_range")

    venue = testnet_venues()[0]
    selected_symbols = {
        symbol: instrument
        for instrument in venue.instruments.instruments
        if instrument.base in bases
        and (symbol := venue.instruments.symbol_for(instrument)) is not None
    }
    # Reconstructing the map keeps the subscription allowlist restricted to the saved AgentSpec.
    instruments = InstrumentMap(selected_symbols)
    sink = _BoundedSampleSink()
    pipeline = IngestionPipeline(
        parser=venue.parser,
        transport=PublicWebSocketTransport(venue.url),
        instruments=instruments,
        channels=venue.channels,
        sinks=[sink],
        config=PipelineConfig(
            batch_size=200,
            flush_interval=timedelta(milliseconds=250),
            max_reconnects=0,
        ),
    )
    try:
        try:
            async with asyncio.timeout(duration_seconds):
                await pipeline.run()
        except TimeoutError:
            pass
    finally:
        await pipeline.aclose()

    events = tuple(event for event in sink.events if isinstance(event, MarketTrade | BookTicker))
    observed = {event.instrument_id.base for event in events if isinstance(event, BookTicker)}
    if observed != set(bases):
        raise TestnetSampleUnavailable("testnet_sample_missing_book")
    return events
