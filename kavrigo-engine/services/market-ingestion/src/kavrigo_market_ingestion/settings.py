"""Ingestion service settings.

Public market data only, so there are no credentials here. The venue and instrument list is
explicit configuration rather than discovery: symbols are mapped, never inferred, and a service
that subscribes to whatever a venue offers would ingest instruments no agent asked for and no
data licence was checked for (``MASTER_BUILD_SPEC.md`` §8.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kavrigo_domain import InstrumentId
from kavrigo_marketdata import (
    BINANCE_MARKET_DATA_WS_URL,
    BINANCE_VENUE,
    BinanceSpotParser,
    Channel,
    InstrumentMap,
    VenueParser,
)

__all__ = ["VenueConfig", "default_venues"]


@dataclass(slots=True)
class VenueConfig:
    """One venue connection: which parser, which URL, which instruments, which channels."""

    venue: str
    url: str
    parser: VenueParser
    instruments: InstrumentMap
    channels: tuple[Channel, ...] = (Channel.TRADES, Channel.BOOK_TICKER)
    candle_interval: str = "1m"
    license_ref: str | None = None
    """Which data-licence entry permits use of this feed (``docs/product/data-license-matrix.md``).
    ``None`` means unconfirmed — acceptable in development, a launch blocker in production."""

    provider: str = field(default="")

    def __post_init__(self) -> None:
        if not self.provider:
            self.provider = self.venue.lower()


def default_venues() -> list[VenueConfig]:
    """Local-development BTC/ETH feed selected after the 2026-09-21 terms review.

    Coinbase is deliberately absent: its current market-data terms prohibit this AI-agent and
    third-party application use without written consent. Binance remains local-development only
    while commercial display, derived-data and retention rights are unconfirmed.
    """
    return [
        VenueConfig(
            venue=BINANCE_VENUE,
            url=BINANCE_MARKET_DATA_WS_URL,
            parser=BinanceSpotParser(),
            instruments=InstrumentMap(
                {
                    "BTCUSDT": InstrumentId.parse("BTC-USDT.BINANCE"),
                    "ETHUSDT": InstrumentId.parse("ETH-USDT.BINANCE"),
                }
            ),
        ),
    ]
