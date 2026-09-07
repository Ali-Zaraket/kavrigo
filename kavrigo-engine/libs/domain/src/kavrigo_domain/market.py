"""Normalized market-data events (``MASTER_BUILD_SPEC.md`` §7.1, §7.2, §18.2).

These are the in-process counterparts of the Protobuf messages in
``libs/data-contracts/proto/kavrigo/v1/market.proto``: what a venue adapter produces after
normalisation, before anything is published or stored.

Prices and quantities are exact decimals with units, as everywhere else in the domain. Bounded
scores are floats; money never is.

Three timestamps are kept distinct because freshness and point-in-time correctness depend on
telling them apart (``MASTER_BUILD_SPEC.md`` §8.4, §8.5):

* ``venue_time`` — when the venue says it happened;
* ``received_at`` — when our process read it off the socket;
* the envelope's ``ingested_at`` — when it entered the platform.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from kavrigo_domain.base import DomainModel, UtcDatetime
from kavrigo_domain.identifiers import InstrumentId
from kavrigo_domain.money import ExactDecimal, Price, Quantity

__all__ = [
    "AggressorSide",
    "BookTicker",
    "Candle",
    "MarketTrade",
]


class AggressorSide(StrEnum):
    """Which side crossed the spread — the taker.

    This is the field that order-flow signals depend on (CVD, taker buy/sell imbalance,
    market-order intensity — ``MASTER_BUILD_SPEC.md`` §7.2). Venues report it differently and
    some report the *maker* side instead, so every adapter must convert explicitly rather than
    pass a venue field through. ``UNKNOWN`` exists because a venue that does not say must not be
    guessed at: a fabricated aggressor silently corrupts every order-flow feature built on it.
    """

    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"

    @property
    def signed_multiplier(self) -> Decimal:
        """+1 for taker buys, -1 for taker sells, 0 when unknown.

        Zero for ``UNKNOWN`` so that unattributed volume contributes nothing to cumulative
        delta rather than biasing it in either direction.
        """
        if self is AggressorSide.BUY:
            return Decimal(1)
        if self is AggressorSide.SELL:
            return Decimal(-1)
        return Decimal(0)


class MarketTrade(DomainModel):
    """One executed public trade."""

    instrument_id: InstrumentId
    price: Price
    quantity: Quantity
    aggressor: AggressorSide = AggressorSide.UNKNOWN
    venue_trade_id: Annotated[str | None, Field(default=None, max_length=64)] = None
    venue_time: UtcDatetime
    received_at: UtcDatetime
    sequence: Annotated[int | None, Field(default=None, ge=0)] = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.quantity.value <= 0:
            raise ValueError("trade quantity must be positive")
        if self.quantity.asset != self.instrument_id.base:
            raise ValueError("trade quantity asset must be the instrument's base asset")
        if (self.price.base, self.price.quote) != (
            self.instrument_id.base,
            self.instrument_id.quote,
        ):
            raise ValueError("trade price assets do not match the instrument")
        return self

    @property
    def notional(self) -> ExactDecimal:
        """Traded value in the quote currency."""
        return self.price.value * self.quantity.value

    @property
    def signed_quantity(self) -> ExactDecimal:
        """Quantity signed by aggressor, the building block of cumulative volume delta."""
        return self.quantity.value * self.aggressor.signed_multiplier


class BookTicker(DomainModel):
    """Best bid and ask.

    Top of book only. ``MASTER_BUILD_SPEC.md`` §7.2 is explicit that displayed liquidity can be
    cancelled, so this is combined with executed trades rather than trusted on its own.
    """

    instrument_id: InstrumentId
    bid_price: Price
    bid_size: Quantity
    ask_price: Price
    ask_size: Quantity
    venue_time: UtcDatetime | None = None
    received_at: UtcDatetime
    sequence: Annotated[int | None, Field(default=None, ge=0)] = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.bid_price.value >= self.ask_price.value:
            # A crossed or locked book from a single venue's top-of-book feed means the frames
            # were reordered or the parse is wrong. Accepting it would produce negative spreads
            # and nonsense microstructure features downstream.
            raise ValueError(
                f"crossed book: bid {self.bid_price.value} >= ask {self.ask_price.value}"
            )
        expected = (self.instrument_id.base, self.instrument_id.quote)
        for label, price in (("bid", self.bid_price), ("ask", self.ask_price)):
            if (price.base, price.quote) != expected:
                raise ValueError(f"{label} price assets do not match the instrument")
        for label, size in (("bid", self.bid_size), ("ask", self.ask_size)):
            if size.asset != self.instrument_id.base:
                raise ValueError(f"{label} size asset must be the instrument's base asset")
            if size.value < 0:
                raise ValueError(f"{label} size must not be negative")
        return self

    @property
    def mid_price(self) -> ExactDecimal:
        return (self.bid_price.value + self.ask_price.value) / Decimal(2)

    @property
    def spread(self) -> ExactDecimal:
        return self.ask_price.value - self.bid_price.value

    @property
    def spread_bps(self) -> ExactDecimal:
        """Spread in basis points of the mid price — the form risk policy compares against."""
        return (self.spread / self.mid_price) * Decimal(10_000)

    @property
    def imbalance(self) -> ExactDecimal:
        """Top-of-book size imbalance in [-1, 1]; zero when both sides are empty."""
        total = self.bid_size.value + self.ask_size.value
        if total == 0:
            return Decimal(0)
        return (self.bid_size.value - self.ask_size.value) / total


class Candle(DomainModel):
    """An OHLCV bar.

    ``is_closed`` is load-bearing rather than informational: consuming an unclosed bar as if it
    were final is look-ahead bias (``MASTER_BUILD_SPEC.md`` §12.3), because its close, high and
    low can all still change.
    """

    instrument_id: InstrumentId
    interval: Annotated[str, Field(pattern=r"^\d+[smhdwM]$")]
    open: ExactDecimal
    high: ExactDecimal
    low: ExactDecimal
    close: ExactDecimal
    volume: ExactDecimal
    quote_volume: ExactDecimal | None = None
    taker_buy_base_volume: ExactDecimal | None = None
    trade_count: Annotated[int | None, Field(default=None, ge=0)] = None
    open_time: UtcDatetime
    close_time: UtcDatetime
    received_at: UtcDatetime
    is_closed: bool

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.close_time <= self.open_time:
            raise ValueError("candle close_time must be after open_time")
        if self.low > self.high:
            raise ValueError(f"candle low {self.low} exceeds high {self.high}")
        for label, value in (("open", self.open), ("close", self.close)):
            if not (self.low <= value <= self.high):
                raise ValueError(f"candle {label} {value} is outside the low/high range")
        optional_volumes: tuple[tuple[str, Decimal | None], ...] = (
            ("volume", self.volume),
            ("quote_volume", self.quote_volume),
            ("taker_buy_base_volume", self.taker_buy_base_volume),
        )
        for label, amount in optional_volumes:
            if amount is not None and amount < 0:
                raise ValueError(f"candle {label} must not be negative")
        if self.taker_buy_base_volume is not None and self.taker_buy_base_volume > self.volume:
            raise ValueError("taker buy volume cannot exceed total volume")
        return self
