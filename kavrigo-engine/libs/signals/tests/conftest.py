"""Builders for feature tests.

Every input is constructed explicitly with exact decimals so expected values can be verified by
hand — a golden-value test whose expectation was produced by the code under test proves nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from kavrigo_domain import (
    AggressorSide,
    BookTicker,
    Candle,
    InstrumentId,
    MarketTrade,
    Price,
    Quantity,
)

AS_OF = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
BTC = InstrumentId.parse("BTC-USDT.BINANCE")
ETH = InstrumentId.parse("ETH-USDT.BINANCE")


def trade(
    *,
    price: str,
    quantity: str = "1",
    ago: timedelta = timedelta(0),
    aggressor: AggressorSide = AggressorSide.BUY,
    instrument: InstrumentId = BTC,
    received_lag: timedelta = timedelta(0),
    as_of: datetime = AS_OF,
) -> MarketTrade:
    """A trade that happened ``ago`` before ``as_of``.

    ``received_lag`` models venue and network latency: the platform knew about the trade later
    than it happened, which is the gap a naive backtest erases.
    """
    venue_time = as_of - ago
    return MarketTrade(
        instrument_id=instrument,
        price=Price(value=Decimal(price), base=instrument.base, quote=instrument.quote),
        quantity=Quantity(value=Decimal(quantity), asset=instrument.base),
        aggressor=aggressor,
        venue_time=venue_time,
        received_at=venue_time + received_lag,
    )


def quote(
    *,
    bid: str,
    ask: str,
    bid_size: str = "1",
    ask_size: str = "1",
    ago: timedelta = timedelta(0),
    instrument: InstrumentId = BTC,
    as_of: datetime = AS_OF,
) -> BookTicker:
    return BookTicker(
        instrument_id=instrument,
        bid_price=Price(value=Decimal(bid), base=instrument.base, quote=instrument.quote),
        bid_size=Quantity(value=Decimal(bid_size), asset=instrument.base),
        ask_price=Price(value=Decimal(ask), base=instrument.base, quote=instrument.quote),
        ask_size=Quantity(value=Decimal(ask_size), asset=instrument.base),
        venue_time=as_of - ago,
        received_at=as_of - ago,
    )


def candle(
    *,
    close: str,
    ago: timedelta = timedelta(minutes=1),
    is_closed: bool = True,
    instrument: InstrumentId = BTC,
    as_of: datetime = AS_OF,
) -> Candle:
    close_time = as_of - ago
    value = Decimal(close)
    return Candle(
        instrument_id=instrument,
        interval="1m",
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("1"),
        open_time=close_time - timedelta(minutes=1),
        close_time=close_time,
        received_at=close_time,
        is_closed=is_closed,
    )


@pytest.fixture
def as_of() -> datetime:
    return AS_OF
