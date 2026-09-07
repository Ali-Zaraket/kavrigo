"""Evaluation metrics.

Expected values are derived from the definition by hand. Spec §12.5 is explicit that raw P&L
must not approve an agent, so these check that the metrics which *would* catch a bad strategy
actually do, and that they refuse to report a number when the sample cannot support one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from kavrigo_backtest import EquityPoint, TradeOutcome, compute_metrics
from kavrigo_domain import Money

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _usdt(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency="USDT")


def _curve(*equities: str, exposure: str = "0") -> list[EquityPoint]:
    return [
        EquityPoint(at=T0 + timedelta(days=i), equity=_usdt(value), exposure=_usdt(exposure))
        for i, value in enumerate(equities)
    ]


def _trade(net: str, *, notional: str = "1000", fees: str = "5") -> TradeOutcome:
    return TradeOutcome(
        instrument_id="BTC-USDT.BINANCE",
        opened_at=T0,
        closed_at=T0 + timedelta(hours=1),
        net_pnl=_usdt(net),
        gross_pnl=_usdt(str(Decimal(net) + Decimal(fees))),
        fees=_usdt(fees),
        notional=_usdt(notional),
    )


class TestReturns:
    def test_net_return_is_fractional_and_after_costs(self) -> None:
        metrics = compute_metrics(
            curve=_curve("10000", "11000"), trades=[], total_fees=_usdt("100")
        )
        assert metrics.net_return == Decimal("0.1")

    def test_gross_return_adds_the_fees_back(self) -> None:
        """A gross figure is an upper bound nobody can trade — reported only for contrast."""
        metrics = compute_metrics(
            curve=_curve("10000", "11000"), trades=[], total_fees=_usdt("100")
        )
        assert metrics.gross_return == Decimal("0.11")
        assert metrics.gross_return > metrics.net_return

    def test_a_loss_is_negative(self) -> None:
        metrics = compute_metrics(curve=_curve("10000", "7500"), trades=[], total_fees=_usdt("0"))
        assert metrics.net_return == Decimal("-0.25")

    def test_an_empty_curve_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least two points"):
            compute_metrics(curve=_curve("10000"), trades=[], total_fees=_usdt("0"))


class TestBenchmark:
    def test_a_gain_below_the_benchmark_is_underperformance(self) -> None:
        """40% in a period the benchmark returned 60% is losing. A report without the
        benchmark hides that."""
        metrics = compute_metrics(
            curve=_curve("10000", "14000"),
            trades=[],
            total_fees=_usdt("0"),
            benchmark_return=Decimal("0.6"),
        )
        assert metrics.net_return == Decimal("0.4")
        assert metrics.excess_return == Decimal("-0.2")
        assert metrics.beat_benchmark is False

    def test_a_loss_above_the_benchmark_is_outperformance(self) -> None:
        metrics = compute_metrics(
            curve=_curve("10000", "9500"),
            trades=[],
            total_fees=_usdt("0"),
            benchmark_return=Decimal("-0.20"),
        )
        assert metrics.beat_benchmark is True

    def test_no_benchmark_reports_unknown_not_false(self) -> None:
        """Reporting an absent comparison as a loss would be as wrong as reporting a win."""
        metrics = compute_metrics(curve=_curve("10000", "11000"), trades=[], total_fees=_usdt("0"))
        assert metrics.beat_benchmark is None
        assert metrics.unavailable["excess_return"] == "no benchmark supplied"


class TestDrawdown:
    def test_it_is_measured_from_the_running_peak(self) -> None:
        """Doubling and then halving loses 50% of what was held. Measuring from the start
        would report break-even and hide the experience of holding it."""
        metrics = compute_metrics(
            curve=_curve("10000", "20000", "10000"), trades=[], total_fees=_usdt("0")
        )
        assert metrics.net_return == 0
        assert metrics.max_drawdown == Decimal("0.5")

    def test_a_monotonic_curve_has_no_drawdown(self) -> None:
        metrics = compute_metrics(
            curve=_curve("10000", "11000", "12000"), trades=[], total_fees=_usdt("0")
        )
        assert metrics.max_drawdown == 0

    def test_the_worst_trough_wins(self) -> None:
        metrics = compute_metrics(
            curve=_curve("100", "90", "100", "60", "100"), trades=[], total_fees=_usdt("0")
        )
        assert metrics.max_drawdown == Decimal("0.4")


class TestRatiosRefuseSmallSamples:
    def test_a_short_run_reports_unavailable_not_a_number(self) -> None:
        """A Sharpe of 4.0 from six observations would approve on noise."""
        metrics = compute_metrics(
            curve=_curve(*[str(10000 + i * 10) for i in range(6)]),
            trades=[],
            total_fees=_usdt("0"),
        )
        assert metrics.sharpe is None
        assert metrics.volatility is None
        assert "needs 20" in metrics.unavailable["sharpe"]

    def test_a_long_enough_run_computes_them(self) -> None:
        curve = _curve(*[str(10000 + (i * 37) % 500) for i in range(40)])
        metrics = compute_metrics(curve=curve, trades=[], total_fees=_usdt("0"))
        assert metrics.volatility is not None
        assert metrics.sharpe is not None
        assert metrics.observation_count == 39

    def test_zero_volatility_makes_sharpe_undefined(self) -> None:
        """Not infinity, and not a large number somebody might promote on."""
        metrics = compute_metrics(curve=_curve(*["10000"] * 30), trades=[], total_fees=_usdt("0"))
        assert metrics.sharpe is None
        assert metrics.unavailable["sharpe"] == "zero volatility"

    def test_sortino_needs_losing_periods(self) -> None:
        curve = _curve(*[str(10000 + i * 10) for i in range(30)])
        metrics = compute_metrics(curve=curve, trades=[], total_fees=_usdt("0"))
        assert metrics.sortino is None
        assert "negative periods" in metrics.unavailable["sortino"]

    def test_expected_shortfall_reports_the_bad_tail(self) -> None:
        curve = _curve(*[str(v) for v in [10000, *[10000 - i * 5 for i in range(1, 30)]]])
        metrics = compute_metrics(curve=curve, trades=[], total_fees=_usdt("0"))
        assert metrics.expected_shortfall_5pct is not None
        assert metrics.expected_shortfall_5pct < 0


class TestTradeStatistics:
    def test_wins_losses_and_rate(self) -> None:
        trades = [_trade("100"), _trade("50"), _trade("-40")]
        metrics = compute_metrics(
            curve=_curve("10000", "10110"), trades=trades, total_fees=_usdt("15")
        )
        assert metrics.trade_count == 3
        assert metrics.win_count == 2
        assert metrics.loss_count == 1
        assert metrics.win_rate is not None
        assert metrics.win_rate == Decimal(2) / Decimal(3)

    def test_profit_factor_is_gross_profit_over_gross_loss(self) -> None:
        """150 won against 50 lost = 3."""
        trades = [_trade("100"), _trade("50"), _trade("-50")]
        metrics = compute_metrics(
            curve=_curve("10000", "10100"), trades=trades, total_fees=_usdt("15")
        )
        assert metrics.profit_factor == Decimal("3")

    def test_no_losing_trades_makes_profit_factor_undefined(self) -> None:
        """Infinity invites promotion on a sample with no downside observed at all."""
        metrics = compute_metrics(
            curve=_curve("10000", "10150"),
            trades=[_trade("100"), _trade("50")],
            total_fees=_usdt("10"),
        )
        assert metrics.profit_factor is None
        assert "no losing trades" in metrics.unavailable["profit_factor"]

    def test_average_trade(self) -> None:
        metrics = compute_metrics(
            curve=_curve("10000", "10110"),
            trades=[_trade("100"), _trade("-40")],
            total_fees=_usdt("10"),
        )
        assert metrics.average_trade == Money(amount=Decimal("30"), currency="USDT")

    def test_turnover_is_traded_notional_over_starting_equity(self) -> None:
        trades = [_trade("10", notional="5000"), _trade("10", notional="5000")]
        metrics = compute_metrics(
            curve=_curve("10000", "10020"), trades=trades, total_fees=_usdt("0")
        )
        assert metrics.turnover == Decimal("1")

    def test_mixed_currencies_in_a_trade_are_refused(self) -> None:
        with pytest.raises(ValueError, match="mixed currencies"):
            TradeOutcome(
                instrument_id="BTC-USDT.BINANCE",
                opened_at=T0,
                closed_at=T0 + timedelta(hours=1),
                net_pnl=_usdt("10"),
                gross_pnl=Money(amount=Decimal("15"), currency="USD"),
                fees=_usdt("5"),
                notional=_usdt("1000"),
            )


class TestExposure:
    def test_average_exposure_is_a_fraction_of_equity(self) -> None:
        metrics = compute_metrics(
            curve=_curve("10000", "10000", exposure="5000"), trades=[], total_fees=_usdt("0")
        )
        assert metrics.average_exposure == Decimal("0.5")

    def test_a_flat_strategy_has_zero_exposure(self) -> None:
        metrics = compute_metrics(curve=_curve("10000", "10000"), trades=[], total_fees=_usdt("0"))
        assert metrics.average_exposure == 0


class TestNoActivity:
    def test_a_run_with_no_trades_reports_honestly(self) -> None:
        """Not a Sharpe of zero and not a win rate of zero — those are claims about a
        strategy that never acted."""
        metrics = compute_metrics(curve=_curve("10000", "10000"), trades=[], total_fees=_usdt("0"))
        assert metrics.net_return == 0
        assert metrics.trade_count == 0
        assert metrics.win_rate is None
        assert metrics.sharpe is None
        assert metrics.unavailable["win_rate"] == "no completed trades"
