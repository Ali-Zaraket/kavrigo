"""Point-in-time market windows.

The single rule this module enforces: **a feature may only see what the platform actually knew
at ``as_of``** (``MASTER_BUILD_SPEC.md`` §12.3, §8.5). That is what separates a backtest from a
fiction, and it is enforced by construction rather than by discipline — an event that arrived
after ``as_of`` cannot get into a window.

Knowability is measured by ``received_at``, not ``venue_time``. A trade that happened at
12:00:00 but reached us at 12:00:03 was not knowable at 12:00:01, and filtering on venue time
would leak three seconds of the future into every decision. The gap between the two is exactly
the venue and network latency that a live system suffers and a naive backtest ignores.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from kavrigo_domain import BookTicker, Candle, InstrumentId, MarketTrade

__all__ = ["InstrumentWindow", "MarketFrame"]


@dataclass(frozen=True, slots=True)
class InstrumentWindow:
    """Everything knowable about one instrument at ``as_of``, newest last."""

    instrument_id: InstrumentId
    as_of: datetime
    trades: tuple[MarketTrade, ...] = ()
    quotes: tuple[BookTicker, ...] = ()
    candles: tuple[Candle, ...] = ()

    @classmethod
    def build(
        cls,
        instrument_id: InstrumentId,
        as_of: datetime,
        *,
        trades: Iterable[MarketTrade] = (),
        quotes: Iterable[BookTicker] = (),
        candles: Iterable[Candle] = (),
    ) -> InstrumentWindow:
        """Filter to what was knowable at ``as_of`` and sort into event order.

        Sorting by ``received_at`` rather than ``venue_time`` keeps the window in the order the
        platform actually observed, which is the order a live run would have seen.

        Sort keys extend past the timestamp into content, giving a **total** order. Sorting on
        the timestamp alone is only a partial order: Python's sort is stable, so events sharing a
        millisecond keep their input order, and the same set delivered in a different order would
        pick a different "latest" trade and compute different features. Ingestion does deliver
        out of order, so that would make a replay disagree with the original run.
        """
        return cls(
            instrument_id=instrument_id,
            as_of=as_of,
            trades=tuple(sorted(_knowable(trades, as_of), key=_trade_key)),
            quotes=tuple(sorted(_knowable(quotes, as_of), key=_quote_key)),
            candles=tuple(
                sorted(
                    # An unclosed bar is not a fact yet: its close, high and low can still
                    # change, so admitting one would be look-ahead bias (spec 12.3).
                    (c for c in _knowable(candles, as_of) if c.is_closed),
                    key=_candle_key,
                )
            ),
        )

    def trades_within(self, lookback: timedelta) -> tuple[MarketTrade, ...]:
        cutoff = self.as_of - lookback
        return tuple(t for t in self.trades if t.received_at > cutoff)

    def quotes_within(self, lookback: timedelta) -> tuple[BookTicker, ...]:
        cutoff = self.as_of - lookback
        return tuple(q for q in self.quotes if q.received_at > cutoff)

    def candles_within(self, lookback: timedelta) -> tuple[Candle, ...]:
        cutoff = self.as_of - lookback
        return tuple(c for c in self.candles if c.close_time > cutoff)

    @property
    def latest_quote(self) -> BookTicker | None:
        return self.quotes[-1] if self.quotes else None

    @property
    def latest_trade(self) -> MarketTrade | None:
        return self.trades[-1] if self.trades else None

    @property
    def span(self) -> timedelta:
        """How much history the window actually holds.

        Features check this before computing: a one-hour return over four minutes of data is not
        a small error, it is a different quantity.
        """
        stamps = [
            *(t.received_at for t in self.trades),
            *(q.received_at for q in self.quotes),
            *(c.close_time for c in self.candles),
        ]
        return self.as_of - min(stamps) if stamps else timedelta(0)

    def covers(self, lookback: timedelta) -> bool:
        return self.span >= lookback


@dataclass(frozen=True, slots=True)
class MarketFrame:
    """Windows for every instrument in a universe, sharing one ``as_of``.

    Relative-strength features need more than one instrument, and every window must share the
    same ``as_of`` — comparing an asset priced at 12:00 against a benchmark priced at 12:05
    would manufacture outperformance out of a timing difference.
    """

    as_of: datetime
    windows: dict[str, InstrumentWindow] = field(default_factory=dict)

    @classmethod
    def of(cls, as_of: datetime, windows: Sequence[InstrumentWindow]) -> MarketFrame:
        for window in windows:
            if window.as_of != as_of:
                raise ValueError(
                    f"window for {window.instrument_id.value} has as_of {window.as_of.isoformat()}, "
                    f"expected {as_of.isoformat()}; mixing decision times fabricates signal"
                )
        return cls(as_of=as_of, windows={w.instrument_id.value: w for w in windows})

    def window_for(self, instrument_id: InstrumentId | str) -> InstrumentWindow | None:
        key = instrument_id if isinstance(instrument_id, str) else instrument_id.value
        return self.windows.get(key)

    @property
    def instruments(self) -> list[InstrumentId]:
        return [w.instrument_id for w in self.windows.values()]


def _knowable[T: (MarketTrade, BookTicker, Candle)](
    events: Iterable[T], as_of: datetime
) -> list[T]:
    """Keep only events the platform had received by ``as_of``."""
    return [event for event in events if event.received_at <= as_of]


# Total sort orders. Two events that genuinely arrived in the same millisecond have no true
# order, so a content-derived tiebreak is arbitrary — but it is the *same* arbitrary choice
# every time, which is what reproducibility requires. `sequence` leads the tiebreak because
# where a venue supplies one it is the venue's own ordering.
_NO_SEQUENCE = -1


def _trade_key(trade: MarketTrade) -> tuple[datetime, int, datetime, Decimal, Decimal, str]:
    return (
        trade.received_at,
        trade.sequence if trade.sequence is not None else _NO_SEQUENCE,
        trade.venue_time,
        trade.price.value,
        trade.quantity.value,
        trade.aggressor.value,
    )


def _quote_key(quote: BookTicker) -> tuple[datetime, int, Decimal, Decimal, Decimal, Decimal]:
    return (
        quote.received_at,
        quote.sequence if quote.sequence is not None else _NO_SEQUENCE,
        quote.bid_price.value,
        quote.ask_price.value,
        quote.bid_size.value,
        quote.ask_size.value,
    )


def _candle_key(candle: Candle) -> tuple[datetime, datetime, Decimal, Decimal]:
    return (candle.close_time, candle.open_time, candle.close, candle.volume)
