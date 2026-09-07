"""Kavrigo market-data adapters, normalization and stream health.

Public market data only. Nothing in this package holds an exchange credential or can reach a
venue's trading endpoints — order placement lives behind the separate
``kavrigo-execution-security`` boundary (ADR 0017).

Venue message formats are transcribed from official documentation, with the source URL and the
verification date recorded in each adapter module. Nothing here is written from recollection of
a venue API (``AGENTS.md`` § Engineering workflow).
"""

from __future__ import annotations

from kavrigo_marketdata.adapter import (
    Channel,
    InstrumentMap,
    MarketEvent,
    ParsedFrame,
    VenueParser,
)
from kavrigo_marketdata.binance import (
    BINANCE_SPOT_WS_URL,
    BINANCE_VENUE,
    BinanceSpotParser,
)
from kavrigo_marketdata.coinbase import (
    COINBASE_VENUE,
    COINBASE_WS_URL,
    CoinbaseExchangeParser,
)
from kavrigo_marketdata.health import (
    SequenceVerdict,
    StreamHealth,
    StreamHealthMonitor,
    StreamKey,
    StreamState,
)
from kavrigo_marketdata.replay import (
    RecordedFrame,
    iter_recorded_frames,
    replay_events,
    replayed_market_events,
    write_recording,
)
from kavrigo_marketdata.transport import (
    ScriptedTransport,
    Transport,
    TransportClosed,
    backoff_delays,
)

__version__ = "0.1.0"

__all__ = [
    "BINANCE_SPOT_WS_URL",
    "BINANCE_VENUE",
    "COINBASE_VENUE",
    "COINBASE_WS_URL",
    "BinanceSpotParser",
    "Channel",
    "CoinbaseExchangeParser",
    "InstrumentMap",
    "MarketEvent",
    "ParsedFrame",
    "RecordedFrame",
    "ScriptedTransport",
    "SequenceVerdict",
    "StreamHealth",
    "StreamHealthMonitor",
    "StreamKey",
    "StreamState",
    "Transport",
    "TransportClosed",
    "VenueParser",
    "__version__",
    "backoff_delays",
    "iter_recorded_frames",
    "replay_events",
    "replayed_market_events",
    "write_recording",
]
