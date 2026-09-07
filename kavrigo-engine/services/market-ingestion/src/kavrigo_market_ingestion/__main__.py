"""Run market ingestion: ``python -m kavrigo_market_ingestion``.

A live WebSocket transport is not wired in yet — see the module note below — so this entry point
currently validates configuration, reports what it *would* subscribe to, and exits. That is
deliberately visible rather than a stub that appears to run.
"""

from __future__ import annotations

import asyncio
import os

import structlog

from kavrigo_market_ingestion.settings import default_venues

_log = structlog.get_logger("kavrigo.ingestion")


async def _run() -> None:
    if os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true":
        raise SystemExit(
            "LIVE_TRADING_ENABLED=true is refused; live execution is gated (ADR 0001)."
        )

    for venue in default_venues():
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

    _log.warning(
        "live_transport_not_wired",
        detail=(
            "Adapters, normalization, health and sinks are implemented and tested against "
            "recorded frames. A production WebSocket transport with reconnect and keepalive is "
            "the next slice."
        ),
    )


def main() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    asyncio.run(_run())


if __name__ == "__main__":
    main()
