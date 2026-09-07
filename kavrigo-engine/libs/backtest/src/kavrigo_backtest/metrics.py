"""Performance evaluation (``MASTER_BUILD_SPEC.md`` §12.5).

"Do not approve based on raw P&L." A strategy can post a large return by taking one enormous
risk, by trading a period that suited it, or by beating nothing at all — so the metrics here are
built to make those cases visible rather than to produce a single flattering number.

Three choices worth stating:

* **Everything is net of costs.** A gross figure is not a result, it is an upper bound nobody
  can trade.
* **Every ratio can be unavailable.** A Sharpe over four observations is noise; returning
  ``None`` with a reason is honest where returning a number is not.
* **Benchmark-relative from the start.** A 40% return in a period the benchmark returned 60% is
  underperformance, and a report that omits the benchmark hides that.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise
from typing import Annotated, Self

from pydantic import Field, model_validator

from kavrigo_domain import (
    DECIMAL_CONTEXT,
    DomainModel,
    ExactDecimal,
    Money,
    UtcDatetime,
    mean,
    safe_divide,
    stdev,
)

__all__ = [
    "EquityPoint",
    "PerformanceMetrics",
    "TradeOutcome",
    "compute_metrics",
]

_ZERO = Decimal(0)
_ONE = Decimal(1)


class EquityPoint(DomainModel):
    """Account equity at a point in time, net of everything."""

    at: UtcDatetime
    equity: Money
    exposure: Money
    """Absolute gross exposure at this point, for the exposure statistics."""


class TradeOutcome(DomainModel):
    """One completed round trip, net of fees and slippage."""

    instrument_id: Annotated[str, Field(min_length=1, max_length=64)]
    opened_at: UtcDatetime
    closed_at: UtcDatetime
    net_pnl: Money
    gross_pnl: Money
    fees: Money
    notional: Money

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.closed_at < self.opened_at:
            raise ValueError("closed_at precedes opened_at")
        currencies = {
            self.net_pnl.currency,
            self.gross_pnl.currency,
            self.fees.currency,
            self.notional.currency,
        }
        if len(currencies) != 1:
            raise ValueError(f"mixed currencies in a trade outcome: {sorted(currencies)}")
        return self

    @property
    def is_win(self) -> bool:
        return self.net_pnl.amount > 0


class PerformanceMetrics(DomainModel):
    """The evaluation record for one run.

    Ratios are ``None`` when the sample cannot support them. That is a deliberate contrast with
    the usual convention of emitting a number regardless: a promotion gate reading a Sharpe of
    4.0 computed from six trades would approve on noise.
    """

    # --- returns -----------------------------------------------------------
    net_return: ExactDecimal
    """Fractional return over the whole period, after costs."""
    gross_return: ExactDecimal
    benchmark_return: ExactDecimal | None = None
    excess_return: ExactDecimal | None = None
    """Net minus benchmark. The number that says whether the agent added anything."""

    total_fees: Money
    starting_equity: Money
    ending_equity: Money
    peak_equity: Money

    # --- risk --------------------------------------------------------------
    max_drawdown: Annotated[ExactDecimal, Field(ge=Decimal(0), le=Decimal(1))]
    volatility: ExactDecimal | None = None
    downside_volatility: ExactDecimal | None = None
    sharpe: ExactDecimal | None = None
    sortino: ExactDecimal | None = None
    expected_shortfall_5pct: ExactDecimal | None = None
    """Mean of the worst 5% of period returns — what a bad stretch actually costs."""

    # --- activity ----------------------------------------------------------
    trade_count: Annotated[int, Field(ge=0)]
    win_count: Annotated[int, Field(ge=0)]
    loss_count: Annotated[int, Field(ge=0)]
    win_rate: ExactDecimal | None = None
    profit_factor: ExactDecimal | None = None
    average_trade: Money | None = None
    turnover: ExactDecimal | None = None
    average_exposure: ExactDecimal | None = None

    # --- honesty -----------------------------------------------------------
    observation_count: Annotated[int, Field(ge=0)]
    unavailable: dict[str, str] = {}
    """Metrics that could not be computed, and why."""

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.win_count + self.loss_count > self.trade_count:
            raise ValueError("wins plus losses exceed the trade count")
        return self

    @property
    def beat_benchmark(self) -> bool | None:
        """``None`` when no benchmark was supplied — not ``False``.

        Reporting an absent comparison as a loss would be as wrong as reporting it as a win.
        """
        if self.excess_return is None:
            return None
        return self.excess_return > 0


def _period_returns(curve: Sequence[EquityPoint]) -> list[Decimal]:
    """Fractional return between consecutive equity observations."""
    returns: list[Decimal] = []
    for previous, current in pairwise(curve):
        if previous.equity.amount <= 0:
            continue
        ratio = safe_divide(current.equity.amount, previous.equity.amount)
        if ratio is None:
            continue
        returns.append(DECIMAL_CONTEXT.subtract(ratio, _ONE))
    return returns


def _max_drawdown(curve: Sequence[EquityPoint]) -> Decimal:
    """Largest peak-to-trough decline as a fraction of the running peak.

    Measured against the running peak rather than the starting equity: a strategy that doubles
    and then halves has lost 50% of what it had, and reporting that as break-even would hide the
    experience of holding it.
    """
    peak = _ZERO
    worst = _ZERO
    for point in curve:
        equity = point.equity.amount
        if equity > peak:
            peak = equity
        if peak > 0:
            drop = safe_divide(DECIMAL_CONTEXT.subtract(peak, equity), peak)
            if drop is not None and drop > worst:
                worst = drop
    return worst


def _expected_shortfall(returns: Sequence[Decimal], tail: Decimal) -> Decimal | None:
    """Mean of the worst ``tail`` fraction of returns."""
    if not returns:
        return None
    count = max(1, int(len(returns) * tail))
    worst = sorted(returns)[:count]
    return mean(worst)


def compute_metrics(
    *,
    curve: Sequence[EquityPoint],
    trades: Sequence[TradeOutcome],
    total_fees: Money,
    benchmark_return: Decimal | None = None,
    risk_free_rate_per_period: Decimal = _ZERO,
    min_observations_for_ratios: int = 20,
) -> PerformanceMetrics:
    """Compute the evaluation record for a run.

    ``min_observations_for_ratios`` guards Sharpe, Sortino, volatility and expected shortfall.
    Twenty is not a magic number and is not enough for statistical confidence either — it is the
    point below which the figures are obviously meaningless, and a promotion gate should require
    far more. The guard exists so that a short run reports "unavailable" rather than a number
    somebody might act on.
    """
    if len(curve) < 2:
        raise ValueError("an equity curve needs at least two points to be evaluated")

    unavailable: dict[str, str] = {}
    starting, ending = curve[0].equity, curve[-1].equity
    if starting.currency != ending.currency:
        raise ValueError("equity curve changes currency")

    net_ratio = safe_divide(ending.amount, starting.amount)
    if net_ratio is None:
        raise ValueError("starting equity is zero; a return is undefined")
    net_return = DECIMAL_CONTEXT.subtract(net_ratio, _ONE)

    gross_ending = DECIMAL_CONTEXT.add(ending.amount, total_fees.amount)
    gross_ratio = safe_divide(gross_ending, starting.amount)
    gross_return = (
        DECIMAL_CONTEXT.subtract(gross_ratio, _ONE) if gross_ratio is not None else net_return
    )

    returns = _period_returns(curve)
    enough = len(returns) >= min_observations_for_ratios
    reason = f"{len(returns)} return observations, needs {min_observations_for_ratios}"

    volatility = stdev(returns) if enough else None
    if not enough:
        unavailable["volatility"] = reason

    downside = [r for r in returns if r < 0]
    downside_volatility = stdev(downside) if enough and len(downside) >= 2 else None
    if enough and downside_volatility is None:
        # A run with fewer than two losing periods has no measurable downside dispersion. That
        # is not a Sortino of infinity; it is an unmeasured quantity.
        unavailable["downside_volatility"] = "fewer than two negative periods"
    elif not enough:
        unavailable["downside_volatility"] = reason

    average_return = mean(returns) if enough else None
    excess_per_period = (
        DECIMAL_CONTEXT.subtract(average_return, risk_free_rate_per_period)
        if average_return is not None
        else None
    )

    sharpe = None
    if excess_per_period is not None and volatility is not None and volatility > 0:
        sharpe = safe_divide(excess_per_period, volatility)
    elif enough:
        unavailable["sharpe"] = "zero volatility" if volatility == 0 else reason
    else:
        unavailable["sharpe"] = reason

    sortino = None
    if (
        excess_per_period is not None
        and downside_volatility is not None
        and downside_volatility > 0
    ):
        sortino = safe_divide(excess_per_period, downside_volatility)
    elif "downside_volatility" in unavailable:
        unavailable["sortino"] = unavailable["downside_volatility"]
    else:
        unavailable["sortino"] = reason

    shortfall = _expected_shortfall(returns, Decimal("0.05")) if enough else None
    if not enough:
        unavailable["expected_shortfall_5pct"] = reason

    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win and t.net_pnl.amount < 0]
    win_rate = safe_divide(Decimal(len(wins)), Decimal(len(trades))) if trades else None
    if not trades:
        unavailable["win_rate"] = "no completed trades"

    gross_profit = _ZERO
    gross_loss = _ZERO
    for trade in wins:
        gross_profit = DECIMAL_CONTEXT.add(gross_profit, trade.net_pnl.amount)
    for trade in losses:
        gross_loss = DECIMAL_CONTEXT.add(gross_loss, abs(trade.net_pnl.amount))
    profit_factor = safe_divide(gross_profit, gross_loss)
    if profit_factor is None:
        # No losing trades. Infinity is not a useful report, and pretending the factor is huge
        # invites a promotion decision on a sample with no downside observed at all.
        unavailable["profit_factor"] = "no losing trades to divide by"

    average_trade = None
    if trades:
        total = _ZERO
        for trade in trades:
            total = DECIMAL_CONTEXT.add(total, trade.net_pnl.amount)
        per_trade = safe_divide(total, Decimal(len(trades)))
        if per_trade is not None:
            average_trade = Money(amount=per_trade, currency=trades[0].net_pnl.currency)

    traded_notional = _ZERO
    for trade in trades:
        traded_notional = DECIMAL_CONTEXT.add(traded_notional, abs(trade.notional.amount))
    turnover = safe_divide(traded_notional, starting.amount)

    exposures = [safe_divide(abs(p.exposure.amount), p.equity.amount) for p in curve]
    usable_exposures = [e for e in exposures if e is not None]
    average_exposure = mean(usable_exposures) if usable_exposures else None
    if average_exposure is None:
        unavailable["average_exposure"] = "no valuable equity observations"

    excess_return = (
        DECIMAL_CONTEXT.subtract(net_return, benchmark_return)
        if benchmark_return is not None
        else None
    )
    if benchmark_return is None:
        unavailable["excess_return"] = "no benchmark supplied"

    return PerformanceMetrics(
        net_return=net_return,
        gross_return=gross_return,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
        total_fees=total_fees,
        starting_equity=starting,
        ending_equity=ending,
        peak_equity=Money(
            amount=max((p.equity.amount for p in curve), default=starting.amount),
            currency=starting.currency,
        ),
        max_drawdown=_max_drawdown(curve),
        volatility=volatility,
        downside_volatility=downside_volatility,
        sharpe=sharpe,
        sortino=sortino,
        expected_shortfall_5pct=shortfall,
        trade_count=len(trades),
        win_count=len(wins),
        loss_count=len(losses),
        win_rate=win_rate,
        profit_factor=profit_factor,
        average_trade=average_trade,
        turnover=turnover,
        average_exposure=average_exposure,
        observation_count=len(returns),
        unavailable=unavailable,
    )
