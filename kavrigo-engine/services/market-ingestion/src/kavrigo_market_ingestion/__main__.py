"""Inspect feed configuration, or explicitly sample public streams without persistence."""

from __future__ import annotations

import asyncio
import os

import structlog

from kavrigo_market_ingestion.pipeline import IngestionPipeline
from kavrigo_market_ingestion.settings import VenueConfig, default_venues
from kavrigo_market_ingestion.sinks import CountingSink
from kavrigo_marketdata import PublicWebSocketTransport

_log = structlog.get_logger("kavrigo.ingestion")


async def _sample_venue(venue: VenueConfig, duration_seconds: int) -> None:
    sink = CountingSink()
    pipeline = IngestionPipeline(
        parser=venue.parser,
        transport=PublicWebSocketTransport(venue.url),
        instruments=venue.instruments,
        channels=venue.channels,
        sinks=[sink],
    )
    try:
        try:
            async with asyncio.timeout(duration_seconds):
                await pipeline.run()
        except TimeoutError:
            pass
        _log.info(
            "ephemeral_market_sample_complete",
            venue=venue.venue,
            frames=pipeline.stats.frames,
            events=pipeline.stats.events,
            skipped=pipeline.stats.skipped,
            reconnects=pipeline.stats.reconnects,
            # Never log sample prices or identifiers. Provider rights are unconfirmed.
        )
    finally:
        await pipeline.aclose()


async def _run() -> None:
    if os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true":
        raise SystemExit(
            "LIVE_TRADING_ENABLED=true is refused; live execution is gated (ADR 0001)."
        )

    venues = default_venues()
    for venue in venues:
        streams = venue.parser.stream_names(
            venue.instruments, venue.channels, interval=venue.candle_interval
        )
        _log.info(
            "venue_configured",
            venue=venue.venue,
            url=venue.url,
            instruments=[i.value for i in venue.instruments.instruments],
            streams=streams,
            license_ref=venue.license_ref or "UNCONFIRMED",
        )
        if venue.license_ref is None:
            # Public development use is one thing; displaying or redistributing the data is
            # another, and it is a launch blocker (MASTER_BUILD_SPEC.md 8.3).
            _log.warning("venue_license_unconfirmed", venue=venue.venue)

    requested = os.getenv("KAVRIGO_INGESTION_SAMPLE_SECONDS")
    if requested is None:
        _log.info(
            "ingestion_config_only",
            detail="Set KAVRIGO_ENV=local and KAVRIGO_INGESTION_SAMPLE_SECONDS=1..60 for an ephemeral feed sample.",
        )
        return
    if os.getenv("KAVRIGO_ENV") != "local" or not requested.isascii() or not requested.isdecimal():
        raise SystemExit("Ephemeral feed sampling requires local mode and a 1..60 second duration.")
    duration_seconds = int(requested)
    if not 1 <= duration_seconds <= 60:
        raise SystemExit("Ephemeral feed sampling requires a 1..60 second duration.")
    async with asyncio.TaskGroup() as group:
        for venue in venues:
            group.create_task(_sample_venue(venue, duration_seconds))


def main() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    asyncio.run(_run())


if __name__ == "__main__":
    main()
