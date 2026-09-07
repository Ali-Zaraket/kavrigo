"""Run the engine worker: ``python -m kavrigo_engine_worker``.

Today this only proves the container starts, loads the domain contracts, and idles without
touching a venue or a credential. Real consumers are added service by service.
"""

from __future__ import annotations

import asyncio
import os
import signal

import structlog

from kavrigo_engine_worker import __version__

_log = structlog.get_logger("kavrigo.engine.worker")


async def _run() -> None:
    if os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true":
        raise SystemExit(
            "LIVE_TRADING_ENABLED=true is refused; live execution is gated (ADR 0001)."
        )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    _log.info("worker_started", version=__version__, mode="paper", consumers=0)
    await stop.wait()
    _log.info("worker_stopped")


def main() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    asyncio.run(_run())


if __name__ == "__main__":
    main()
