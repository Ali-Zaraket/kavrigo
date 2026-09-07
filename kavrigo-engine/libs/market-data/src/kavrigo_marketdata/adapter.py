"""Venue adapter interfaces.

A venue adapter has exactly one job: turn a venue's wire frames into normalized domain events.
It does not publish, store, retry, or decide anything — those belong to the ingestion service —
so that adding a venue is a parsing exercise with a fixture file, not a distributed-systems one.

Two rules the interfaces exist to enforce:

* **Symbols are mapped, never inferred.** ``BTCUSDT`` cannot be split into base and quote
  without knowing the venue's quote assets, and guessing produces an instrument that silently
  refers to the wrong market. Adapters resolve venue symbols through an
  :class:`InstrumentMap` built from what was actually subscribed.
* **Unknown frames are skipped, not crashed on.** Venues add message types without notice. A
  parser that raises on an unrecognised frame turns a cosmetic upstream change into an
  ingestion outage.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from kavrigo_domain import BookTicker, Candle, InstrumentId, MarketTrade

__all__ = [
    "Channel",
    "InstrumentMap",
    "MarketEvent",
    "ParsedFrame",
    "VenueParser",
]

MarketEvent = MarketTrade | BookTicker | Candle


class Channel(StrEnum):
    """The data a subscription asks for.

    Deliberately small. Depth-of-book and derivatives channels are added when the features that
    need them are built, not speculatively (``MASTER_BUILD_SPEC.md`` §7).
    """

    TRADES = "trades"
    BOOK_TICKER = "book_ticker"
    CANDLES = "candles"


class InstrumentMap:
    """Venue symbol ↔ :class:`InstrumentId`, built from an explicit subscription.

    Both directions are needed: outbound to build stream names, inbound to resolve the symbol on
    a frame. Nothing is inferred — an unknown symbol resolves to ``None`` and its frame is
    dropped, because a frame we did not subscribe to is either a venue change or a bug, and
    inventing an instrument for it would be worse than losing it.
    """

    def __init__(self, pairs: Mapping[str, InstrumentId]) -> None:
        self._by_symbol: dict[str, InstrumentId] = {}
        self._by_instrument: dict[str, str] = {}
        for symbol, instrument in pairs.items():
            # Venues differ in case (Binance streams are lowercase, payloads uppercase), so the
            # lookup is case-insensitive while the outbound symbol keeps the venue's own casing.
            self._by_symbol[symbol.upper()] = instrument
            self._by_instrument[instrument.value] = symbol

    def instrument_for(self, symbol: str) -> InstrumentId | None:
        return self._by_symbol.get(symbol.upper())

    def symbol_for(self, instrument: InstrumentId) -> str | None:
        return self._by_instrument.get(instrument.value)

    @property
    def instruments(self) -> list[InstrumentId]:
        return list(self._by_symbol.values())

    @property
    def symbols(self) -> list[str]:
        return list(self._by_instrument.values())

    def __len__(self) -> int:
        return len(self._by_symbol)


class ParsedFrame:
    """The outcome of parsing one wire frame.

    A frame can legitimately produce no event — subscription acknowledgements, heartbeats and
    control messages all do — so "no event" and "parse failed" are distinct outcomes rather than
    both being ``None``.
    """

    __slots__ = ("event", "is_control", "reason", "sequence")

    def __init__(
        self,
        event: MarketEvent | None = None,
        *,
        is_control: bool = False,
        reason: str | None = None,
        sequence: int | None = None,
    ) -> None:
        self.event = event
        self.is_control = is_control
        self.reason = reason
        self.sequence = sequence

    @property
    def is_skipped(self) -> bool:
        return self.event is None and not self.is_control


@runtime_checkable
class VenueParser(Protocol):
    """Turns one venue's frames into normalized events."""

    venue: str

    def stream_names(
        self, instruments: InstrumentMap, channels: tuple[Channel, ...], *, interval: str
    ) -> list[str]:
        """Venue-specific stream identifiers for a subscription."""
        ...

    def subscribe_payloads(
        self, instruments: InstrumentMap, channels: tuple[Channel, ...], *, interval: str
    ) -> list[dict[str, Any]]:
        """Messages to send after connecting, if the venue requires them."""
        ...

    def parse(
        self, frame: Mapping[str, Any], *, received_at: datetime, instruments: InstrumentMap
    ) -> ParsedFrame:
        """Parse one decoded frame. Must not raise on unrecognised input."""
        ...
