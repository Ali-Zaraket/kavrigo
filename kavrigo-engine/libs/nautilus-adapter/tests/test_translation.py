"""Translation across the engine boundary.

Unit conversions are where realism is quietly lost: a factor of 10,000 on fees or 1,000,000 on
latency produces a backtest that is wrong by orders of magnitude and still looks plausible.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from nautilus_trader.model.enums import AggressorSide as NautilusAggressorSide

from kavrigo_backtest import (
    CostModel,
    FeeSchedule,
    LatencyModel,
    LiquidityAssumption,
    SlippageModel,
)
from kavrigo_domain import AggressorSide
from kavrigo_nautilus import (
    NANOS_PER_MILLI,
    bps_to_rate,
    to_nautilus_aggressor,
    to_nautilus_fill_model,
    to_nautilus_latency_model,
)


def _costs(**overrides: object) -> CostModel:
    values: dict[str, object] = {
        "fees": FeeSchedule(venue="BINANCE", maker_bps=Decimal("1"), taker_bps=Decimal("10")),
        "slippage": SlippageModel(spread_crossing_bps=Decimal("2")),
        "latency": LatencyModel(decision_to_venue_ms=50, venue_ack_ms=10),
    }
    values.update(overrides)
    return CostModel(**values)  # type: ignore[arg-type]


class TestFeeConversion:
    @pytest.mark.parametrize(
        ("bps", "rate"), [("10", "0.001"), ("1", "0.0001"), ("0", "0"), ("-2", "-0.0002")]
    )
    def test_basis_points_to_rate(self, bps: str, rate: str) -> None:
        assert bps_to_rate(Decimal(bps)) == Decimal(rate)

    def test_the_conversion_is_exact(self) -> None:
        """Routing this through a float would reintroduce the error the decimal types exist to
        prevent."""
        assert isinstance(bps_to_rate(Decimal("7.5")), Decimal)
        assert bps_to_rate(Decimal("7.5")) == Decimal("0.00075")


class TestAggressorMapping:
    def test_the_taker_side_is_not_re_inverted(self) -> None:
        """Our venue adapters already inverted Binance's `m` and Coinbase's maker-side `side`.
        Both sides here are the taker, and this mapping must preserve that."""
        assert to_nautilus_aggressor(AggressorSide.BUY) == NautilusAggressorSide.BUYER
        assert to_nautilus_aggressor(AggressorSide.SELL) == NautilusAggressorSide.SELLER

    def test_unknown_maps_to_no_aggressor(self) -> None:
        assert to_nautilus_aggressor(AggressorSide.UNKNOWN) == NautilusAggressorSide.NO_AGGRESSOR

    def test_every_side_is_mapped(self) -> None:
        for side in AggressorSide:
            assert to_nautilus_aggressor(side) is not None


class TestLatencyConversion:
    def test_milliseconds_become_nanoseconds(self) -> None:
        model = to_nautilus_latency_model(LatencyModel(decision_to_venue_ms=50, venue_ack_ms=10))
        assert model.base_latency_nanos == 50 * NANOS_PER_MILLI

    def test_nautilus_composes_the_legs_additively(self) -> None:
        """Verified against 1.231.0: the reported insert latency is base + insert.

        So the effective insert latency is decision_to_venue + venue_ack, which is the intended
        total. Passing an already-summed value would double-count the base leg and make every
        simulated order arrive later than the cost model claims.
        """
        model = to_nautilus_latency_model(LatencyModel(decision_to_venue_ms=50, venue_ack_ms=10))
        assert model.insert_latency_nanos == 60 * NANOS_PER_MILLI
        assert model.insert_latency_nanos == model.base_latency_nanos + 10 * NANOS_PER_MILLI

    def test_an_ack_free_model_leaves_the_base_leg_alone(self) -> None:
        model = to_nautilus_latency_model(LatencyModel(decision_to_venue_ms=50, venue_ack_ms=0))
        assert model.insert_latency_nanos == 50 * NANOS_PER_MILLI

    def test_the_nautilus_one_second_default_is_overridden(self) -> None:
        """Left at its default it would dominate any figure set elsewhere."""
        model = to_nautilus_latency_model(LatencyModel(decision_to_venue_ms=5))
        assert model.base_latency_nanos == 5 * NANOS_PER_MILLI
        assert model.base_latency_nanos != 1_000_000_000

    def test_zero_latency_translates_to_zero(self) -> None:
        model = to_nautilus_latency_model(LatencyModel(decision_to_venue_ms=0))
        assert model.base_latency_nanos == 0


class TestFillModel:
    def test_the_seed_is_pinned(self) -> None:
        """A probabilistic fill model must still be reproducible (spec 12.2)."""
        first = to_nautilus_fill_model(_costs(), random_seed=42)
        second = to_nautilus_fill_model(_costs(), random_seed=42)
        assert first.prob_slippage == second.prob_slippage
        assert first.prob_fill_on_limit == second.prob_fill_on_limit

    def test_spread_crossing_enables_slippage(self) -> None:
        assert to_nautilus_fill_model(_costs(), random_seed=0).prob_slippage > 0

    def test_a_mid_fill_assumption_disables_slippage(self) -> None:
        """A cost model asserting mid fills has already excluded spread cost; the fill model
        should not then add it back on top of that assumption."""
        mid = _costs(slippage=SlippageModel(spread_crossing_bps=Decimal("0")))
        assert to_nautilus_fill_model(mid, random_seed=0).prob_slippage == 0

    def test_the_optimistic_liquidity_assumption_always_fills_limits(self) -> None:
        optimistic = _costs(liquidity=LiquidityAssumption.ALWAYS_MAKER)
        assert to_nautilus_fill_model(optimistic, random_seed=0).prob_fill_on_limit == 1.0
        assert to_nautilus_fill_model(_costs(), random_seed=0).prob_fill_on_limit < 1.0
