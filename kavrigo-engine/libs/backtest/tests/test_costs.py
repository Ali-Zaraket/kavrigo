"""Cost, slippage and latency models — the assumptions that decide whether a backtest lies."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from kavrigo_backtest import (
    CostModel,
    FeeSchedule,
    LatencyModel,
    LiquidityAssumption,
    SlippageModel,
)
from kavrigo_domain import Money

from .conftest import cost_model


class TestFees:
    def test_maker_and_taker_are_distinct(self, default_costs: CostModel) -> None:
        assert default_costs.fees.rate_bps(is_maker=True) == Decimal("1")
        assert default_costs.fees.rate_bps(is_maker=False) == Decimal("10")

    def test_a_taker_fee_below_maker_is_refused(self) -> None:
        """Not a real venue schedule; almost always a swapped argument."""
        with pytest.raises(ValidationError, match="taker fee below maker fee"):
            FeeSchedule(venue="X", maker_bps=Decimal("10"), taker_bps=Decimal("1"))

    def test_a_maker_rebate_is_representable(self) -> None:
        schedule = FeeSchedule(venue="X", maker_bps=Decimal("-2"), taker_bps=Decimal("7"))
        assert schedule.rate_bps(is_maker=True) == Decimal("-2")


class TestSlippage:
    def test_spread_crossing_is_charged(self) -> None:
        model = SlippageModel(spread_crossing_bps=Decimal("3"))
        assert model.slippage_bps() == Decimal("3")

    def test_impact_scales_with_participation(self) -> None:
        model = SlippageModel(
            spread_crossing_bps=Decimal("2"), impact_bps_per_unit_adv=Decimal("100")
        )
        # 2 bps to cross, plus 100 bps per unit of ADV at 5% participation = 5 bps.
        assert model.slippage_bps(participation_of_adv=Decimal("0.05")) == Decimal("7.00")

    def test_negative_participation_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot be negative"):
            SlippageModel(spread_crossing_bps=Decimal("2")).slippage_bps(
                participation_of_adv=Decimal("-1")
            )


class TestLatency:
    def test_round_trip_sums_every_leg(self) -> None:
        latency = LatencyModel(decision_to_venue_ms=50, venue_ack_ms=10, market_data_ms=20)
        assert latency.total_round_trip_ms == 80
        assert not latency.is_zero

    def test_zero_latency_is_detectable(self) -> None:
        """The single most flattering assumption available: fills at the price that triggered
        the decision."""
        assert LatencyModel(decision_to_venue_ms=0).is_zero


class TestRoundTripCost:
    def test_both_legs_are_charged(self, default_costs: CostModel) -> None:
        """A position that is opened is eventually closed. Quoting a one-way cost halves the
        apparent hurdle."""
        one_way = default_costs.one_way_cost()
        round_trip = default_costs.round_trip_cost()
        assert one_way.total_bps == Decimal("12")  # 10 taker + 2 crossing
        assert round_trip.total_bps == Decimal("24")

    def test_maker_assumption_is_cheaper(self, default_costs: CostModel) -> None:
        assert (
            default_costs.round_trip_cost(is_maker=True).total_bps
            < default_costs.round_trip_cost(is_maker=False).total_bps
        )

    def test_absolute_cost_for_a_notional(self, default_costs: CostModel) -> None:
        """24 bps of 10,000 USDT is 24 USDT."""
        cost = default_costs.round_trip_cost().cost_for(
            Money(amount=Decimal("10000"), currency="USDT")
        )
        assert cost == Money(amount=Decimal("24.0000"), currency="USDT")


class TestOptimismWarnings:
    def test_a_conservative_model_warns_about_nothing(self, default_costs: CostModel) -> None:
        assert default_costs.optimism_warnings == []
        assert default_costs.is_conservative

    def test_zero_latency_is_flagged(self) -> None:
        model = cost_model(latency=LatencyModel(decision_to_venue_ms=0))
        assert any(w.startswith("zero_latency") for w in model.optimism_warnings)
        assert not model.is_conservative

    def test_always_maker_is_flagged(self) -> None:
        model = cost_model(liquidity=LiquidityAssumption.ALWAYS_MAKER)
        assert any(w.startswith("always_maker") for w in model.optimism_warnings)

    def test_rebate_dependence_is_flagged(self) -> None:
        model = cost_model(
            fees=FeeSchedule(venue="X", maker_bps=Decimal("-2"), taker_bps=Decimal("7")),
            liquidity=LiquidityAssumption.ALWAYS_MAKER,
        )
        assert any(w.startswith("rebate_dependent") for w in model.optimism_warnings)

    def test_mid_fills_are_flagged(self) -> None:
        model = cost_model(slippage=SlippageModel(spread_crossing_bps=Decimal("0")))
        assert any(w.startswith("no_spread_crossing") for w in model.optimism_warnings)

    def test_no_partial_fills_is_flagged(self) -> None:
        model = cost_model(partial_fills_enabled=False)
        assert any(w.startswith("no_partial_fills") for w in model.optimism_warnings)

    def test_warnings_accumulate(self) -> None:
        model = cost_model(
            latency=LatencyModel(decision_to_venue_ms=0),
            slippage=SlippageModel(spread_crossing_bps=Decimal("0")),
            liquidity=LiquidityAssumption.ALWAYS_MAKER,
        )
        assert len(model.optimism_warnings) >= 3
