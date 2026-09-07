"""Feature computations.

Every function here is deterministic, decimal, and point-in-time: it reads only from an
:class:`InstrumentWindow`, which by construction contains only what was knowable at ``as_of``.

Two conventions run through all of them:

* **Insufficient data returns ``None`` with a reason, never a number.** A one-hour return
  computed over four minutes of data is not slightly wrong, it is a different quantity.
  Returning zero would be a specific, false claim, and downstream an unavailable feature drives
  abstention while a fabricated zero drives a trade.
* **A lookback is measured against a base observation, not against the oldest row present.**
  "Return over 5 minutes" means "price now versus the last price at or before 5 minutes ago", so
  a window that happens to start 90 seconds ago cannot masquerade as five minutes of history.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise

from kavrigo_domain import AggressorSide, MarketTrade
from kavrigo_domain.numeric import FEATURE_CONTEXT, mean, safe_divide, stdev, to_bps
from kavrigo_signals.registry import FeatureValue
from kavrigo_signals.window import InstrumentWindow, MarketFrame

__all__ = [
    "book_imbalance",
    "cumulative_volume_delta",
    "realized_volatility",
    "relative_strength",
    "simple_return",
    "spread_bps",
    "taker_buy_ratio",
    "traded_volume",
    "volume_zscore",
    "vwap",
]

_ZERO = Decimal(0)


def _unavailable(name: str, reason: str) -> FeatureValue:
    return FeatureValue(name=name, value=None, reason=reason)


def _price_at_or_before(window: InstrumentWindow, moment: datetime) -> Decimal | None:
    """Last traded price the platform had observed at ``moment``.

    Scans backwards because the most recent qualifying trade is usually near the end.
    """
    for trade in reversed(window.trades):
        if trade.received_at <= moment:
            return trade.price.value
    return None


def simple_return(window: InstrumentWindow, lookback: timedelta, name: str) -> FeatureValue:
    """Fractional price change over ``lookback``: ``(now / then) - 1``.

    Simple rather than log return: this is the form position sizing and P&L attribution use, and
    log returns are computed separately where their additivity actually helps (volatility).
    """
    latest = window.latest_trade
    if latest is None:
        return _unavailable(name, "no trades in window")
    if not window.covers(lookback):
        return _unavailable(name, f"window covers {window.span}, needs {lookback}")

    base = _price_at_or_before(window, window.as_of - lookback)
    if base is None:
        return _unavailable(name, "no trade at or before the lookback boundary")
    if base <= 0:
        return _unavailable(name, "non-positive base price")

    ratio = safe_divide(latest.price.value, base)
    if ratio is None:  # pragma: no cover - guarded above
        return _unavailable(name, "undefined ratio")
    return FeatureValue(name=name, value=FEATURE_CONTEXT.subtract(ratio, Decimal(1)))


def vwap(window: InstrumentWindow, lookback: timedelta, name: str) -> FeatureValue:
    """Volume-weighted average price over ``lookback``.

    The reference price a fill should be judged against; comparing an execution to the last
    trade instead flatters or punishes it by whatever the last print happened to be.
    """
    trades = window.trades_within(lookback)
    if not trades:
        return _unavailable(name, "no trades in lookback")

    notional, quantity = _ZERO, _ZERO
    for trade in trades:
        notional = FEATURE_CONTEXT.add(
            notional, FEATURE_CONTEXT.multiply(trade.price.value, trade.quantity.value)
        )
        quantity = FEATURE_CONTEXT.add(quantity, trade.quantity.value)

    value = safe_divide(notional, quantity)
    if value is None:
        return _unavailable(name, "zero traded quantity")
    return FeatureValue(name=name, value=value)


def traded_volume(window: InstrumentWindow, lookback: timedelta, name: str) -> FeatureValue:
    """Total base-asset volume over ``lookback``."""
    trades = window.trades_within(lookback)
    if not trades:
        return _unavailable(name, "no trades in lookback")
    total = _ZERO
    for trade in trades:
        total = FEATURE_CONTEXT.add(total, trade.quantity.value)
    return FeatureValue(name=name, value=total)


def volume_zscore(
    window: InstrumentWindow,
    lookback: timedelta,
    bucket: timedelta,
    name: str,
    *,
    min_buckets: int = 4,
) -> FeatureValue:
    """How unusual the most recent bucket's volume is, in standard deviations.

    The window is divided into fixed buckets anchored at ``as_of`` — anchoring at the oldest
    observation instead would make the bucket boundaries, and therefore the value, depend on
    when the window happened to start.

    A z-score needs a believable baseline; below ``min_buckets`` observations the standard
    deviation is noise, so the feature reports unavailable rather than a large meaningless
    number.
    """
    if not window.covers(lookback):
        return _unavailable(name, f"window covers {window.span}, needs {lookback}")

    bucket_count = int(lookback / bucket)
    if bucket_count < min_buckets:
        return _unavailable(name, f"{bucket_count} buckets is below the minimum {min_buckets}")

    volumes: list[Decimal] = []
    for index in range(bucket_count):
        end = window.as_of - bucket * index
        start = end - bucket
        total = _ZERO
        for trade in window.trades:
            if start < trade.received_at <= end:
                total = FEATURE_CONTEXT.add(total, trade.quantity.value)
        volumes.append(total)

    latest, baseline = volumes[0], volumes
    spread = stdev(baseline)
    average = mean(baseline)
    if spread is None or average is None:
        return _unavailable(name, "insufficient buckets for a baseline")
    if spread == 0:
        # Every bucket identical. The z-score is undefined, not zero and not infinite.
        return _unavailable(name, "zero variance in the baseline")

    value = safe_divide(FEATURE_CONTEXT.subtract(latest, average), spread)
    if value is None:  # pragma: no cover - guarded above
        return _unavailable(name, "undefined z-score")
    return FeatureValue(name=name, value=value)


def realized_volatility(
    window: InstrumentWindow, lookback: timedelta, name: str, *, min_observations: int = 3
) -> FeatureValue:
    """Standard deviation of log returns between consecutive trades in ``lookback``.

    Log returns because they are additive across time, which is what makes the standard
    deviation of a series of them meaningful.

    Deliberately **not annualised**. Annualising requires assuming an observation frequency, and
    trade arrivals are irregular — the factor would be a modelling choice smuggled into a raw
    feature. Consumers that want an annualised figure apply their own factor, visibly.
    """
    trades = window.trades_within(lookback)
    if len(trades) < min_observations + 1:
        return _unavailable(name, f"{len(trades)} trades, needs at least {min_observations + 1}")
    if not window.covers(lookback):
        return _unavailable(name, f"window covers {window.span}, needs {lookback}")

    log_returns: list[Decimal] = []
    for previous, current in pairwise(trades):
        if previous.price.value <= 0 or current.price.value <= 0:
            continue
        ratio = safe_divide(current.price.value, previous.price.value)
        if ratio is None or ratio <= 0:
            continue
        try:
            log_returns.append(FEATURE_CONTEXT.ln(ratio))
        except (InvalidOperation, ValueError):  # pragma: no cover - guarded by ratio > 0
            continue

    if len(log_returns) < min_observations:
        return _unavailable(name, "not enough usable log returns")
    value = stdev(log_returns)
    if value is None:  # pragma: no cover - guarded by the length check
        return _unavailable(name, "undefined standard deviation")
    return FeatureValue(name=name, value=value)


def spread_bps(window: InstrumentWindow, name: str) -> FeatureValue:
    """Bid-ask spread of the most recent quote, in basis points of the mid.

    Basis points rather than absolute currency so the value is comparable across instruments and
    directly usable by ``RiskLimits.max_spread_bps``.
    """
    quote = window.latest_quote
    if quote is None:
        return _unavailable(name, "no quote in window")
    mid = quote.mid_price
    if mid <= 0:
        return _unavailable(name, "non-positive mid price")
    ratio = safe_divide(quote.spread, mid)
    if ratio is None:  # pragma: no cover - guarded above
        return _unavailable(name, "undefined spread ratio")
    return FeatureValue(name=name, value=to_bps(ratio))


def book_imbalance(window: InstrumentWindow, name: str) -> FeatureValue:
    """Top-of-book size imbalance in [-1, 1]; positive means more size bid than offered.

    Top of book only, and displayed size can be cancelled (``MASTER_BUILD_SPEC.md`` §7.2), so
    this is a weak signal on its own and is meant to be read alongside executed flow.
    """
    quote = window.latest_quote
    if quote is None:
        return _unavailable(name, "no quote in window")
    if quote.bid_size.value + quote.ask_size.value == 0:
        return _unavailable(name, "empty book on both sides")
    return FeatureValue(name=name, value=quote.imbalance)


def cumulative_volume_delta(
    window: InstrumentWindow, lookback: timedelta, name: str
) -> FeatureValue:
    """Signed taker volume over ``lookback``: taker buys minus taker sells.

    Trades whose aggressor is unknown contribute zero rather than being guessed at — attributing
    them arbitrarily would bias the delta in whichever direction was assumed.
    """
    trades = window.trades_within(lookback)
    if not trades:
        return _unavailable(name, "no trades in lookback")
    if all(t.aggressor is AggressorSide.UNKNOWN for t in trades):
        return _unavailable(name, "no trade in the window has an attributed aggressor")

    total = _ZERO
    for trade in trades:
        total = FEATURE_CONTEXT.add(total, trade.signed_quantity)
    return FeatureValue(name=name, value=total)


def taker_buy_ratio(window: InstrumentWindow, lookback: timedelta, name: str) -> FeatureValue:
    """Share of attributed volume that was taker-initiated buying, in [0, 1].

    Unattributed trades are excluded from *both* numerator and denominator: counting them in the
    denominator alone would pull every reading toward zero and understate genuine imbalance.
    """
    trades = window.trades_within(lookback)
    if not trades:
        return _unavailable(name, "no trades in lookback")

    buys, attributed = _ZERO, _ZERO
    for trade in trades:
        if trade.aggressor is AggressorSide.UNKNOWN:
            continue
        attributed = FEATURE_CONTEXT.add(attributed, trade.quantity.value)
        if trade.aggressor is AggressorSide.BUY:
            buys = FEATURE_CONTEXT.add(buys, trade.quantity.value)

    value = safe_divide(buys, attributed)
    if value is None:
        return _unavailable(name, "no attributed volume in lookback")
    return FeatureValue(name=name, value=value)


def relative_strength(
    frame: MarketFrame,
    instrument_key: str,
    benchmark_key: str,
    lookback: timedelta,
    name: str,
) -> FeatureValue:
    """Return of an instrument minus the return of a benchmark over the same window.

    ``MASTER_BUILD_SPEC.md`` §7.17: this is what distinguishes a nominal gain from genuine
    outperformance. An asset up 3% while its benchmark is up 5% is weak, not strong, and a
    strategy reading only the absolute return would draw the opposite conclusion.

    Both legs are computed from windows sharing one ``as_of`` — :meth:`MarketFrame.of` enforces
    that, because comparing across decision times would manufacture outperformance out of a
    timing difference.
    """
    if instrument_key == benchmark_key:
        return _unavailable(name, "an instrument cannot be its own benchmark")

    window = frame.window_for(instrument_key)
    benchmark = frame.window_for(benchmark_key)
    if window is None:
        return _unavailable(name, f"no window for {instrument_key}")
    if benchmark is None:
        return _unavailable(name, f"no window for benchmark {benchmark_key}")

    asset_return = simple_return(window, lookback, name)
    benchmark_return = simple_return(benchmark, lookback, name)
    if asset_return.value is None:
        return _unavailable(name, f"asset return unavailable: {asset_return.reason}")
    if benchmark_return.value is None:
        return _unavailable(name, f"benchmark return unavailable: {benchmark_return.reason}")

    return FeatureValue(
        name=name,
        value=FEATURE_CONTEXT.subtract(asset_return.value, benchmark_return.value),
    )


def _trade_prices(trades: tuple[MarketTrade, ...]) -> list[Decimal]:  # pragma: no cover - helper
    return [t.price.value for t in trades]
