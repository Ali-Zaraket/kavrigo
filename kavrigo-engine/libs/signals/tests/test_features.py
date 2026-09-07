"""Feature formulas, with expected values verifiable by hand.

Golden values are computed from the definition, not from the implementation — a test whose
expectation came out of the code under test proves only that the code is consistent with itself.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from kavrigo_domain import AggressorSide
from kavrigo_signals import InstrumentWindow, MarketFrame
from kavrigo_signals import features as f

from .conftest import AS_OF, BTC, ETH, quote, trade

_5M = timedelta(minutes=5)
_15M = timedelta(minutes=15)
_1H = timedelta(hours=1)


def _window(**kwargs: object) -> InstrumentWindow:
    return InstrumentWindow.build(BTC, AS_OF, **kwargs)  # type: ignore[arg-type]


class TestSimpleReturn:
    def test_a_ten_percent_gain(self) -> None:
        window = _window(
            trades=[
                trade(price="100", ago=timedelta(minutes=6)),
                trade(price="110", ago=timedelta(minutes=1)),
            ]
        )
        assert f.simple_return(window, _5M, "r").value == Decimal("0.1")

    def test_a_loss_is_negative(self) -> None:
        window = _window(
            trades=[
                trade(price="100", ago=timedelta(minutes=6)),
                trade(price="75", ago=timedelta(minutes=1)),
            ]
        )
        assert f.simple_return(window, _5M, "r").value == Decimal("-0.25")

    def test_the_base_is_the_last_price_at_or_before_the_boundary(self) -> None:
        """Not the oldest row present: a window starting 90 seconds ago must not masquerade as
        five minutes of history, and a window with more history must use the right base."""
        window = _window(
            trades=[
                trade(price="50", ago=timedelta(minutes=30)),
                trade(price="100", ago=timedelta(minutes=6)),
                trade(price="105", ago=timedelta(minutes=4)),
                trade(price="110", ago=timedelta(seconds=30)),
            ]
        )
        # Base is the 100 print at t-6m, the last one at or before t-5m.
        assert f.simple_return(window, _5M, "r").value == Decimal("0.1")

    def test_a_window_too_short_is_unavailable_not_zero(self) -> None:
        window = _window(trades=[trade(price="100", ago=timedelta(minutes=2))])
        result = f.simple_return(window, _1H, "r")
        assert result.value is None
        assert result.reason is not None
        assert "needs" in result.reason

    def test_no_trades_is_unavailable(self) -> None:
        assert f.simple_return(_window(), _5M, "r").value is None


class TestVwap:
    def test_it_weights_by_quantity(self) -> None:
        """(100*1 + 200*3) / 4 = 175. An unweighted mean would say 150."""
        window = _window(
            trades=[
                trade(price="100", quantity="1", ago=timedelta(minutes=2)),
                trade(price="200", quantity="3", ago=timedelta(minutes=1)),
            ]
        )
        assert f.vwap(window, _15M, "v").value == Decimal("175")

    def test_no_trades_is_unavailable(self) -> None:
        assert f.vwap(_window(), _15M, "v").value is None


class TestVolume:
    def test_it_sums_base_quantity_in_the_lookback(self) -> None:
        window = _window(
            trades=[
                trade(price="100", quantity="1.5", ago=timedelta(minutes=20)),
                trade(price="100", quantity="2.25", ago=timedelta(minutes=10)),
                trade(price="100", quantity="0.75", ago=timedelta(minutes=1)),
            ]
        )
        assert f.traded_volume(window, _15M, "v").value == Decimal("3.00")


class TestVolumeZscore:
    def _hourly_window(self, latest_quantity: str) -> InstrumentWindow:
        """One trade in each of the twelve 5-minute buckets of the last hour.

        The anchor at 61 minutes gives the window an hour of span without falling into any
        bucket, so the baseline is exactly the twelve in-hour observations.
        """
        anchor = trade(price="100", quantity="1", ago=timedelta(minutes=61))
        buckets = [
            trade(price="100", quantity="1", ago=timedelta(minutes=5 * i + 1)) for i in range(1, 12)
        ]
        latest = trade(price="100", quantity=latest_quantity, ago=timedelta(minutes=1))
        return _window(trades=[anchor, *buckets, latest])

    def test_a_volume_burst_scores_high(self) -> None:
        result = f.volume_zscore(self._hourly_window("10"), _1H, _5M, "z")
        assert result.value is not None
        assert result.value > 3

    def test_flat_volume_has_no_variance_and_is_unavailable(self) -> None:
        """Undefined, not zero and not infinite."""
        result = f.volume_zscore(self._hourly_window("1"), _1H, _5M, "z")
        assert result.value is None
        assert result.reason == "zero variance in the baseline"

    def test_a_short_window_is_unavailable(self) -> None:
        window = _window(trades=[trade(price="100", ago=timedelta(minutes=3))])
        assert f.volume_zscore(window, _1H, _5M, "z").value is None

    def test_too_few_buckets_is_unavailable(self) -> None:
        """A z-score over three buckets is noise, not a baseline."""
        window = _window(
            trades=[trade(price="100", ago=timedelta(minutes=i)) for i in (1, 6, 11, 16, 40)]
        )
        result = f.volume_zscore(window, timedelta(minutes=15), _5M, "z", min_buckets=4)
        assert result.value is None
        assert result.reason is not None
        assert "below the minimum" in result.reason


class TestRealizedVolatility:
    def test_a_constant_price_has_zero_volatility(self) -> None:
        # The 20-minute print gives the window enough span; the rest sit inside the lookback.
        window = _window(
            trades=[trade(price="100", ago=timedelta(minutes=m)) for m in (20, 14, 10, 6, 2, 1)]
        )
        assert f.realized_volatility(window, _15M, "vol").value == 0

    def test_a_moving_price_has_positive_volatility(self) -> None:
        window = _window(
            trades=[
                trade(price=p, ago=timedelta(minutes=m))
                for p, m in [
                    ("100", 20),  # span anchor
                    ("100", 14),
                    ("105", 12),
                    ("98", 8),
                    ("107", 4),
                    ("99", 1),
                ]
            ]
        )
        result = f.realized_volatility(window, _15M, "vol")
        assert result.value is not None
        assert result.value > 0

    def test_it_is_the_stdev_of_log_returns(self) -> None:
        """A constant doubling gives three identical log returns, so dispersion is nil.

        The result is ~1e-28 rather than exactly zero: ln(2) is irrational, so at 28 significant
        digits the mean-and-subtract round trip inside a standard deviation leaves a residue one
        ulp wide. Asserting an exact zero here would be asserting something false about
        fixed-precision arithmetic. A *price* that never moves does give exactly zero, because
        those values are exact — see the test above.
        """
        window = _window(
            trades=[
                trade(price="1", ago=timedelta(minutes=20)),  # span anchor, outside the lookback
                trade(price="100", ago=timedelta(minutes=14)),
                trade(price="200", ago=timedelta(minutes=10)),
                trade(price="400", ago=timedelta(minutes=5)),
                trade(price="800", ago=timedelta(minutes=1)),
            ]
        )
        result = f.realized_volatility(window, _15M, "vol")
        assert result.value is not None
        assert abs(result.value) < Decimal("1e-25")

    def test_too_few_observations_is_unavailable(self) -> None:
        window = _window(
            trades=[
                trade(price="100", ago=timedelta(minutes=20)),
                trade(price="101", ago=timedelta(minutes=1)),
            ]
        )
        assert f.realized_volatility(window, _15M, "vol").value is None


class TestSpread:
    def test_spread_in_basis_points_of_the_mid(self) -> None:
        """bid 99.95, ask 100.05: spread 0.10, mid 100, so 10 bps."""
        window = _window(quotes=[quote(bid="99.95", ask="100.05")])
        assert f.spread_bps(window, "s").value == Decimal("10")

    def test_it_uses_the_most_recent_quote(self) -> None:
        window = _window(
            quotes=[
                quote(bid="90", ask="110", ago=timedelta(minutes=5)),
                quote(bid="99.95", ask="100.05", ago=timedelta(seconds=1)),
            ]
        )
        assert f.spread_bps(window, "s").value == Decimal("10")

    def test_no_quote_is_unavailable(self) -> None:
        assert f.spread_bps(_window(), "s").value is None


class TestBookImbalance:
    def test_more_bid_size_is_positive(self) -> None:
        """(3 - 1) / 4 = 0.5"""
        window = _window(quotes=[quote(bid="100", ask="101", bid_size="3", ask_size="1")])
        assert f.book_imbalance(window, "i").value == Decimal("0.5")

    def test_more_ask_size_is_negative(self) -> None:
        window = _window(quotes=[quote(bid="100", ask="101", bid_size="1", ask_size="3")])
        assert f.book_imbalance(window, "i").value == Decimal("-0.5")

    def test_a_balanced_book_is_zero(self) -> None:
        window = _window(quotes=[quote(bid="100", ask="101", bid_size="2", ask_size="2")])
        assert f.book_imbalance(window, "i").value == 0

    def test_an_empty_book_is_unavailable(self) -> None:
        window = _window(quotes=[quote(bid="100", ask="101", bid_size="0", ask_size="0")])
        assert f.book_imbalance(window, "i").value is None


class TestOrderFlow:
    def test_cvd_nets_taker_buys_against_taker_sells(self) -> None:
        window = _window(
            trades=[
                trade(
                    price="100", quantity="3", aggressor=AggressorSide.BUY, ago=timedelta(minutes=5)
                ),
                trade(
                    price="100",
                    quantity="1",
                    aggressor=AggressorSide.SELL,
                    ago=timedelta(minutes=2),
                ),
            ]
        )
        assert f.cumulative_volume_delta(window, _15M, "cvd").value == Decimal("2")

    def test_unattributed_trades_contribute_nothing_to_cvd(self) -> None:
        """Guessing an aggressor would bias the delta in whichever direction was assumed."""
        window = _window(
            trades=[
                trade(
                    price="100", quantity="3", aggressor=AggressorSide.BUY, ago=timedelta(minutes=5)
                ),
                trade(
                    price="100",
                    quantity="99",
                    aggressor=AggressorSide.UNKNOWN,
                    ago=timedelta(minutes=2),
                ),
            ]
        )
        assert f.cumulative_volume_delta(window, _15M, "cvd").value == Decimal("3")

    def test_cvd_is_unavailable_when_nothing_is_attributed(self) -> None:
        window = _window(
            trades=[trade(price="100", aggressor=AggressorSide.UNKNOWN, ago=timedelta(minutes=1))]
        )
        assert f.cumulative_volume_delta(window, _15M, "cvd").value is None

    def test_taker_buy_ratio_excludes_unattributed_from_both_sides(self) -> None:
        """Counting unknowns in the denominator alone would pull every reading toward zero."""
        window = _window(
            trades=[
                trade(
                    price="100", quantity="3", aggressor=AggressorSide.BUY, ago=timedelta(minutes=5)
                ),
                trade(
                    price="100",
                    quantity="1",
                    aggressor=AggressorSide.SELL,
                    ago=timedelta(minutes=3),
                ),
                trade(
                    price="100",
                    quantity="96",
                    aggressor=AggressorSide.UNKNOWN,
                    ago=timedelta(minutes=1),
                ),
            ]
        )
        assert f.taker_buy_ratio(window, _15M, "r").value == Decimal("0.75")

    def test_taker_buy_ratio_is_unavailable_without_attribution(self) -> None:
        window = _window(
            trades=[trade(price="100", aggressor=AggressorSide.UNKNOWN, ago=timedelta(minutes=1))]
        )
        assert f.taker_buy_ratio(window, _15M, "r").value is None


class TestRelativeStrength:
    def _frame(
        self, asset_prices: tuple[str, str], benchmark_prices: tuple[str, str]
    ) -> MarketFrame:
        def window(instrument, prices):  # type: ignore[no-untyped-def]
            return InstrumentWindow.build(
                instrument,
                AS_OF,
                trades=[
                    trade(price=prices[0], ago=timedelta(minutes=61), instrument=instrument),
                    trade(price=prices[1], ago=timedelta(minutes=1), instrument=instrument),
                ],
            )

        return MarketFrame.of(AS_OF, [window(ETH, asset_prices), window(BTC, benchmark_prices)])

    def test_underperformance_is_negative_despite_a_nominal_gain(self) -> None:
        """Spec 7.17: an asset up 3% while the benchmark is up 5% is weak, not strong. A
        strategy reading only the absolute return would draw the opposite conclusion."""
        frame = self._frame(("100", "103"), ("100", "105"))
        result = f.relative_strength(frame, ETH.value, BTC.value, _1H, "rs")
        assert result.value == Decimal("-0.02")

    def test_outperformance_is_positive_despite_a_nominal_loss(self) -> None:
        frame = self._frame(("100", "98"), ("100", "90"))
        result = f.relative_strength(frame, ETH.value, BTC.value, _1H, "rs")
        assert result.value == Decimal("0.08")

    def test_an_instrument_cannot_benchmark_itself(self) -> None:
        frame = self._frame(("100", "103"), ("100", "105"))
        result = f.relative_strength(frame, BTC.value, BTC.value, _1H, "rs")
        assert result.value is None
        assert result.reason is not None
        assert "own benchmark" in result.reason

    def test_a_missing_benchmark_is_unavailable(self) -> None:
        frame = self._frame(("100", "103"), ("100", "105"))
        result = f.relative_strength(frame, ETH.value, "SOL-USDT.BINANCE", _1H, "rs")
        assert result.value is None

    def test_an_uncomputable_leg_reports_which_one(self) -> None:
        thin = InstrumentWindow.build(
            ETH, AS_OF, trades=[trade(price="100", ago=timedelta(minutes=2), instrument=ETH)]
        )
        rich = InstrumentWindow.build(
            BTC,
            AS_OF,
            trades=[
                trade(price="100", ago=timedelta(minutes=61)),
                trade(price="105", ago=timedelta(minutes=1)),
            ],
        )
        frame = MarketFrame.of(AS_OF, [thin, rich])
        result = f.relative_strength(frame, ETH.value, BTC.value, _1H, "rs")
        assert result.value is None
        assert result.reason is not None
        assert "asset return unavailable" in result.reason
