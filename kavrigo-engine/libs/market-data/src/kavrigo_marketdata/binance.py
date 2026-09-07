"""Binance spot public WebSocket adapter.

Message shapes verified against the official documentation on 2026-09-07:
https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams

* ``<symbol>@trade`` — ``e E s t p q T m M``
* ``<symbol>@bookTicker`` — ``u s b B a A``
* ``<symbol>@kline_<interval>`` — ``e E s k{t T s i f L o c h l v n x q V Q B}``

Combined streams wrap each payload as ``{"stream": ..., "data": ...}``.

Public market data only. This adapter never sees a credential and cannot place an order; venue
execution lives behind the separate ``kavrigo-execution-security`` boundary (ADR 0017).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from kavrigo_domain import (
    AggressorSide,
    BookTicker,
    Candle,
    InstrumentId,
    MarketTrade,
    Price,
    Quantity,
)
from kavrigo_marketdata.adapter import Channel, InstrumentMap, ParsedFrame

__all__ = ["BINANCE_SPOT_WS_URL", "BINANCE_VENUE", "BinanceSpotParser"]

BINANCE_VENUE = "BINANCE"
BINANCE_SPOT_WS_URL = "wss://stream.binance.com:9443/stream"

_CHANNEL_SUFFIX = {
    Channel.TRADES: "trade",
    Channel.BOOK_TICKER: "bookTicker",
}


def _decimal(value: Any) -> Decimal | None:
    """Parse a venue decimal string. Returns ``None`` rather than raising on junk.

    Binance sends numbers as strings precisely so they survive without float rounding, so they
    are parsed as ``Decimal`` and never through ``float``.
    """
    if isinstance(value, str | int):
        try:
            return Decimal(value)
        except InvalidOperation:
            return None
    return None


def _millis(value: Any) -> datetime | None:
    if not isinstance(value, int):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


class BinanceSpotParser:
    """Parses Binance spot public stream frames."""

    venue = BINANCE_VENUE

    def stream_names(
        self, instruments: InstrumentMap, channels: tuple[Channel, ...], *, interval: str = "1m"
    ) -> list[str]:
        names: list[str] = []
        for symbol in instruments.symbols:
            for channel in channels:
                if channel is Channel.CANDLES:
                    names.append(f"{symbol.lower()}@kline_{interval}")
                else:
                    names.append(f"{symbol.lower()}@{_CHANNEL_SUFFIX[channel]}")
        return names

    def subscribe_payloads(
        self, instruments: InstrumentMap, channels: tuple[Channel, ...], *, interval: str = "1m"
    ) -> list[dict[str, Any]]:
        return [
            {
                "method": "SUBSCRIBE",
                "params": self.stream_names(instruments, channels, interval=interval),
                "id": 1,
            }
        ]

    def parse(
        self, frame: Mapping[str, Any], *, received_at: datetime, instruments: InstrumentMap
    ) -> ParsedFrame:
        # Combined-stream frames nest the payload; raw single-stream frames do not.
        payload = frame.get("data") if "data" in frame else frame
        if not isinstance(payload, Mapping):
            return ParsedFrame(reason="frame has no object payload")

        # A subscription acknowledgement is `{"result": null, "id": 1}` — control, not data.
        if "result" in payload or ("id" in payload and "e" not in payload and "u" not in payload):
            return ParsedFrame(is_control=True)

        event_type = payload.get("e")
        if event_type == "trade":
            return self._parse_trade(payload, received_at, instruments)
        if event_type == "kline":
            return self._parse_kline(payload, received_at, instruments)
        # bookTicker frames carry no `e`; they are identified by the update-id field.
        if "u" in payload and "b" in payload and "a" in payload:
            return self._parse_book_ticker(payload, received_at, instruments)
        return ParsedFrame(reason=f"unrecognised event type {event_type!r}")

    def _instrument(
        self, payload: Mapping[str, Any], instruments: InstrumentMap
    ) -> InstrumentId | None:
        symbol = payload.get("s")
        return instruments.instrument_for(symbol) if isinstance(symbol, str) else None

    def _parse_trade(
        self, payload: Mapping[str, Any], received_at: datetime, instruments: InstrumentMap
    ) -> ParsedFrame:
        instrument = self._instrument(payload, instruments)
        if instrument is None:
            return ParsedFrame(reason="unsubscribed or unmappable symbol")

        price = _decimal(payload.get("p"))
        quantity = _decimal(payload.get("q"))
        venue_time = _millis(payload.get("T"))
        if price is None or quantity is None or venue_time is None:
            return ParsedFrame(reason="trade frame missing price, quantity or timestamp")
        if quantity <= 0 or price <= 0:
            return ParsedFrame(reason="trade frame has non-positive price or quantity")

        # `m` is "was the BUYER the market maker?". If so the taker was the seller, so the
        # aggressor is the opposite of what the flag might suggest at a glance. Getting this
        # backwards inverts every order-flow feature built on it.
        maker_is_buyer = payload.get("m")
        if maker_is_buyer is True:
            aggressor = AggressorSide.SELL
        elif maker_is_buyer is False:
            aggressor = AggressorSide.BUY
        else:
            aggressor = AggressorSide.UNKNOWN

        trade_id = payload.get("t")
        return ParsedFrame(
            MarketTrade(
                instrument_id=instrument,
                price=Price(value=price, base=instrument.base, quote=instrument.quote),
                quantity=Quantity(value=quantity, asset=instrument.base),
                aggressor=aggressor,
                venue_trade_id=str(trade_id) if isinstance(trade_id, int) else None,
                venue_time=venue_time,
                received_at=received_at,
                sequence=trade_id if isinstance(trade_id, int) and trade_id >= 0 else None,
            ),
            sequence=trade_id if isinstance(trade_id, int) else None,
        )

    def _parse_book_ticker(
        self, payload: Mapping[str, Any], received_at: datetime, instruments: InstrumentMap
    ) -> ParsedFrame:
        instrument = self._instrument(payload, instruments)
        if instrument is None:
            return ParsedFrame(reason="unsubscribed or unmappable symbol")

        bid, bid_size = _decimal(payload.get("b")), _decimal(payload.get("B"))
        ask, ask_size = _decimal(payload.get("a")), _decimal(payload.get("A"))
        if bid is None or bid_size is None or ask is None or ask_size is None:
            return ParsedFrame(reason="book ticker frame missing a price or size")
        if bid <= 0 or ask <= 0:
            return ParsedFrame(reason="book ticker has a non-positive price")
        if bid >= ask:
            # Reordered frames or a venue anomaly. Dropping is right: a crossed book would
            # produce a negative spread and poison microstructure features.
            return ParsedFrame(reason=f"crossed book: bid {bid} >= ask {ask}")

        update_id = payload.get("u")
        sequence = update_id if isinstance(update_id, int) and update_id >= 0 else None
        return ParsedFrame(
            BookTicker(
                instrument_id=instrument,
                bid_price=Price(value=bid, base=instrument.base, quote=instrument.quote),
                bid_size=Quantity(value=bid_size, asset=instrument.base),
                ask_price=Price(value=ask, base=instrument.base, quote=instrument.quote),
                ask_size=Quantity(value=ask_size, asset=instrument.base),
                # bookTicker carries no venue timestamp of its own; the update id is the
                # ordering signal. Inventing a timestamp here would make data look fresher
                # than it is, which is a risk input (AGENTS.md domain rule 5).
                venue_time=None,
                received_at=received_at,
                sequence=sequence,
            ),
            sequence=sequence,
        )

    def _parse_kline(
        self, payload: Mapping[str, Any], received_at: datetime, instruments: InstrumentMap
    ) -> ParsedFrame:
        instrument = self._instrument(payload, instruments)
        if instrument is None:
            return ParsedFrame(reason="unsubscribed or unmappable symbol")
        kline = payload.get("k")
        if not isinstance(kline, Mapping):
            return ParsedFrame(reason="kline frame has no candle object")

        values = {key: _decimal(kline.get(key)) for key in ("o", "h", "l", "c", "v", "q", "V")}
        open_time, close_time = _millis(kline.get("t")), _millis(kline.get("T"))
        if any(values[k] is None for k in ("o", "h", "l", "c", "v")):
            return ParsedFrame(reason="kline frame missing OHLCV")
        if open_time is None or close_time is None:
            return ParsedFrame(reason="kline frame missing timestamps")

        interval = kline.get("i")
        trade_count = kline.get("n")
        try:
            candle = Candle(
                instrument_id=instrument,
                interval=interval if isinstance(interval, str) else "1m",
                open=values["o"],
                high=values["h"],
                low=values["l"],
                close=values["c"],
                volume=values["v"],
                quote_volume=values["q"],
                taker_buy_base_volume=values["V"],
                trade_count=trade_count if isinstance(trade_count, int) else None,
                open_time=open_time,
                close_time=close_time,
                received_at=received_at,
                # `x` marks a finalised bar. An unclosed bar consumed as final is look-ahead
                # bias (MASTER_BUILD_SPEC.md 12.3), so the flag is carried, never assumed.
                is_closed=bool(kline.get("x")),
            )
        except ValueError as exc:
            return ParsedFrame(reason=f"kline failed validation: {exc}")
        return ParsedFrame(candle)
