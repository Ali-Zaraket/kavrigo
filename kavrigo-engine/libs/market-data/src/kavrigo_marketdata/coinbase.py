"""Coinbase Exchange public WebSocket adapter.

Message shapes verified against the official documentation on 2026-09-07:
https://docs.cdp.coinbase.com/exchange/websocket-feed/channels

* ``match`` — ``type trade_id sequence maker_order_id taker_order_id time product_id size price side``
* ``ticker`` — ``type sequence product_id price ... best_bid best_bid_size best_ask best_ask_size side time trade_id last_size``

Endpoint: ``wss://ws-feed.exchange.coinbase.com`` (public, no authentication). The feed
disconnects a client that has not sent a ``subscribe`` within five seconds of connecting.

**The ``side`` field on a match is the maker's side**, quoting the documentation: *"The side
field indicates the maker order side. If the side is sell this indicates the maker was a sell
order and the match is considered an up-tick."* The aggressor is therefore the opposite, and
this adapter inverts it. Passing the venue field straight through would invert every
order-flow feature built on it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from kavrigo_domain import (
    AggressorSide,
    BookTicker,
    InstrumentId,
    MarketTrade,
    Price,
    Quantity,
)
from kavrigo_marketdata.adapter import Channel, InstrumentMap, ParsedFrame

__all__ = ["COINBASE_VENUE", "COINBASE_WS_URL", "CoinbaseExchangeParser"]

COINBASE_VENUE = "COINBASE"
COINBASE_WS_URL = "wss://ws-feed.exchange.coinbase.com"

_CHANNEL_NAMES = {
    Channel.TRADES: "matches",
    Channel.BOOK_TICKER: "ticker",
}

#: Frames that are protocol chatter rather than market data.
_CONTROL_TYPES = frozenset(
    {"subscriptions", "heartbeat", "status", "error", "received", "open", "done"}
)


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, str | int):
        try:
            return Decimal(value)
        except InvalidOperation:
            return None
    return None


def _timestamp(value: Any) -> datetime | None:
    """Parse Coinbase's ISO-8601 timestamps.

    Coinbase sends a trailing ``Z``; ``fromisoformat`` handles it on modern Python, but the
    result is rejected downstream if it somehow lacks an offset, because a naive timestamp
    breaks every freshness check.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


class CoinbaseExchangeParser:
    """Parses Coinbase Exchange public feed frames."""

    venue = COINBASE_VENUE

    def stream_names(
        self, instruments: InstrumentMap, channels: tuple[Channel, ...], *, interval: str = "1m"
    ) -> list[str]:
        # Coinbase names channels, not per-symbol streams; products are a separate list.
        return [_CHANNEL_NAMES[c] for c in channels if c in _CHANNEL_NAMES]

    def subscribe_payloads(
        self, instruments: InstrumentMap, channels: tuple[Channel, ...], *, interval: str = "1m"
    ) -> list[dict[str, Any]]:
        subscribed = self.stream_names(instruments, channels, interval=interval)
        return [
            {
                "type": "subscribe",
                "product_ids": instruments.symbols,
                # `heartbeat` is requested alongside the data channels because it is how
                # Coinbase surfaces sequence continuity, which is what gap detection needs.
                "channels": [*subscribed, "heartbeat"],
            }
        ]

    def parse(
        self, frame: Mapping[str, Any], *, received_at: datetime, instruments: InstrumentMap
    ) -> ParsedFrame:
        frame_type = frame.get("type")
        if frame_type in ("match", "last_match"):
            return self._parse_match(frame, received_at, instruments)
        if frame_type == "ticker":
            return self._parse_ticker(frame, received_at, instruments)
        if frame_type in _CONTROL_TYPES:
            sequence = frame.get("sequence")
            return ParsedFrame(
                is_control=True,
                sequence=sequence if isinstance(sequence, int) else None,
            )
        return ParsedFrame(reason=f"unrecognised frame type {frame_type!r}")

    def _instrument(
        self, frame: Mapping[str, Any], instruments: InstrumentMap
    ) -> InstrumentId | None:
        product = frame.get("product_id")
        return instruments.instrument_for(product) if isinstance(product, str) else None

    def _parse_match(
        self, frame: Mapping[str, Any], received_at: datetime, instruments: InstrumentMap
    ) -> ParsedFrame:
        instrument = self._instrument(frame, instruments)
        if instrument is None:
            return ParsedFrame(reason="unsubscribed or unmappable product")

        price = _decimal(frame.get("price"))
        size = _decimal(frame.get("size"))
        venue_time = _timestamp(frame.get("time"))
        if price is None or size is None or venue_time is None:
            return ParsedFrame(reason="match frame missing price, size or time")
        if price <= 0 or size <= 0:
            return ParsedFrame(reason="match frame has non-positive price or size")

        # Documented as the MAKER's side, so the taker took the other one.
        maker_side = frame.get("side")
        if maker_side == "sell":
            aggressor = AggressorSide.BUY
        elif maker_side == "buy":
            aggressor = AggressorSide.SELL
        else:
            aggressor = AggressorSide.UNKNOWN

        trade_id = frame.get("trade_id")
        sequence = frame.get("sequence")
        return ParsedFrame(
            MarketTrade(
                instrument_id=instrument,
                price=Price(value=price, base=instrument.base, quote=instrument.quote),
                quantity=Quantity(value=size, asset=instrument.base),
                aggressor=aggressor,
                venue_trade_id=str(trade_id) if isinstance(trade_id, int) else None,
                venue_time=venue_time,
                received_at=received_at,
                sequence=sequence if isinstance(sequence, int) and sequence >= 0 else None,
            ),
            sequence=sequence if isinstance(sequence, int) else None,
        )

    def _parse_ticker(
        self, frame: Mapping[str, Any], received_at: datetime, instruments: InstrumentMap
    ) -> ParsedFrame:
        instrument = self._instrument(frame, instruments)
        if instrument is None:
            return ParsedFrame(reason="unsubscribed or unmappable product")

        bid, bid_size = _decimal(frame.get("best_bid")), _decimal(frame.get("best_bid_size"))
        ask, ask_size = _decimal(frame.get("best_ask")), _decimal(frame.get("best_ask_size"))
        if bid is None or bid_size is None or ask is None or ask_size is None:
            return ParsedFrame(reason="ticker frame missing a best bid/ask price or size")
        if bid <= 0 or ask <= 0:
            return ParsedFrame(reason="ticker has a non-positive price")
        if bid >= ask:
            return ParsedFrame(reason=f"crossed book: bid {bid} >= ask {ask}")

        sequence = frame.get("sequence")
        return ParsedFrame(
            BookTicker(
                instrument_id=instrument,
                bid_price=Price(value=bid, base=instrument.base, quote=instrument.quote),
                bid_size=Quantity(value=bid_size, asset=instrument.base),
                ask_price=Price(value=ask, base=instrument.base, quote=instrument.quote),
                ask_size=Quantity(value=ask_size, asset=instrument.base),
                venue_time=_timestamp(frame.get("time")),
                received_at=received_at,
                sequence=sequence if isinstance(sequence, int) and sequence >= 0 else None,
            ),
            sequence=sequence if isinstance(sequence, int) else None,
        )
