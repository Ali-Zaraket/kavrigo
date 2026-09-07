"""Cost and execution-reality models (``MASTER_BUILD_SPEC.md`` §12.4).

The single largest source of false confidence in a trading platform is a backtest that fills at
the mid, instantly, for free. Every one of the frictions below turns a strategy that "works" into
one that does not, and they compound: a strategy trading 20 times a day at 8bps round-trip needs
roughly 1.6% a day of gross edge simply to break even.

Modelled here:

* **fees** — maker and taker are different numbers, and assuming maker fills is the most common
  way to flatter a backtest;
* **spread** — a market order does not pay the mid, it pays the other side;
* **slippage** — size beyond the top of book walks the book;
* **latency** — the price when the decision was made is not the price when the order arrives.

Every figure is expressed in basis points or explicit currency, never as a vague multiplier, so
a result can be re-run against a different assumption and the sensitivity reported (§12.5).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from kavrigo_domain import DECIMAL_CONTEXT, DomainModel, ExactDecimal, Money

__all__ = [
    "CostModel",
    "FeeSchedule",
    "LatencyModel",
    "LiquidityAssumption",
    "SlippageModel",
    "TradeCost",
]


class LiquidityAssumption(StrEnum):
    """What the simulation assumes about how orders fill.

    ``ALWAYS_MAKER`` is deliberately available *and* deliberately flagged as optimistic: a
    strategy assuming it earns rebates on every fill is assuming its resting orders are always
    hit, which is exactly the assumption that does not survive contact with a real venue.
    """

    ALWAYS_TAKER = "always_taker"
    ALWAYS_MAKER = "always_maker"
    ORDER_TYPE = "order_type"

    @property
    def is_optimistic(self) -> bool:
        return self is LiquidityAssumption.ALWAYS_MAKER


class FeeSchedule(DomainModel):
    """Venue fee tiers in basis points of notional.

    Negative maker fees (rebates) are representable because some venues pay them, but a backtest
    relying on a rebate should say so loudly — see :attr:`CostModel.optimism_warnings`.
    """

    venue: Annotated[str, Field(min_length=1, max_length=32)]
    maker_bps: Annotated[ExactDecimal, Field(ge=Decimal(-50), le=Decimal(500))]
    taker_bps: Annotated[ExactDecimal, Field(ge=Decimal(0), le=Decimal(500))]
    minimum_fee: Money | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.taker_bps < self.maker_bps:
            raise ValueError(
                "taker fee below maker fee is not a real venue schedule; check the inputs"
            )
        return self

    def rate_bps(self, *, is_maker: bool) -> Decimal:
        return self.maker_bps if is_maker else self.taker_bps


class SlippageModel(DomainModel):
    """How far past the touch an order is assumed to fill.

    ``spread_crossing_bps`` is the half-spread a taker pays even for an infinitesimal order.
    ``impact_bps_per_unit_adv`` charges additional slippage in proportion to the order's share of
    average daily volume — a square-root law is closer to reality for large orders, but linear is
    the conservative choice at the sizes this platform targets, and being conservative about cost
    is the correct direction to be wrong in.
    """

    spread_crossing_bps: Annotated[ExactDecimal, Field(ge=Decimal(0), le=Decimal(1000))]
    impact_bps_per_unit_adv: Annotated[ExactDecimal, Field(ge=Decimal(0), le=Decimal(100_000))] = (
        Decimal(0)
    )
    fixed_slippage_bps: Annotated[ExactDecimal, Field(ge=Decimal(0), le=Decimal(1000))] = Decimal(0)

    def slippage_bps(self, *, participation_of_adv: Decimal = Decimal(0)) -> Decimal:
        """Total slippage in basis points for a given participation rate."""
        if participation_of_adv < 0:
            raise ValueError("participation cannot be negative")
        impact = DECIMAL_CONTEXT.multiply(self.impact_bps_per_unit_adv, participation_of_adv)
        return DECIMAL_CONTEXT.add(
            DECIMAL_CONTEXT.add(self.spread_crossing_bps, self.fixed_slippage_bps), impact
        )


class LatencyModel(DomainModel):
    """Delay between deciding and the order reaching the venue.

    Latency is not a performance detail in a backtest, it is a correctness one: with zero
    latency a strategy fills at the price that triggered it, which is the single most flattering
    assumption available. ``decision_to_venue_ms`` is the number that matters.
    """

    decision_to_venue_ms: Annotated[int, Field(ge=0, le=60_000)]
    venue_ack_ms: Annotated[int, Field(ge=0, le=60_000)] = 0
    market_data_ms: Annotated[int, Field(ge=0, le=60_000)] = 0
    """Delay between an event happening and the strategy seeing it."""

    @property
    def total_round_trip_ms(self) -> int:
        return self.market_data_ms + self.decision_to_venue_ms + self.venue_ack_ms

    @property
    def is_zero(self) -> bool:
        return self.total_round_trip_ms == 0


class TradeCost(DomainModel):
    """The modelled cost of one round trip, decomposed so it can be argued with."""

    fee_bps: ExactDecimal
    slippage_bps: ExactDecimal

    @property
    def total_bps(self) -> Decimal:
        return DECIMAL_CONTEXT.add(self.fee_bps, self.slippage_bps)

    def cost_for(self, notional: Money) -> Money:
        """Absolute cost for a given notional."""
        ratio = DECIMAL_CONTEXT.divide(self.total_bps, Decimal(10_000))
        return Money(
            amount=DECIMAL_CONTEXT.multiply(notional.amount, ratio), currency=notional.currency
        )


class CostModel(DomainModel):
    """The complete execution-reality assumption a run was evaluated under.

    Recorded on every result. Two runs are only comparable if they shared a cost model, and a
    published performance figure without one is not a claim about a strategy — it is a claim
    about an assumption.
    """

    fees: FeeSchedule
    slippage: SlippageModel
    latency: LatencyModel
    liquidity: LiquidityAssumption = LiquidityAssumption.ALWAYS_TAKER
    minimum_order_notional: Money | None = None
    partial_fills_enabled: bool = True
    reject_on_insufficient_liquidity: bool = True

    def round_trip_cost(
        self, *, is_maker: bool = False, participation_of_adv: Decimal = Decimal(0)
    ) -> TradeCost:
        """Cost of entering and exiting once.

        Both legs are charged, because a position that is opened is eventually closed. Quoting a
        one-way cost halves the apparent hurdle and is a common way backtests understate it.
        """
        one_way_fee = self.fees.rate_bps(is_maker=is_maker)
        one_way_slippage = self.slippage.slippage_bps(participation_of_adv=participation_of_adv)
        two = Decimal(2)
        return TradeCost(
            fee_bps=DECIMAL_CONTEXT.multiply(one_way_fee, two),
            slippage_bps=DECIMAL_CONTEXT.multiply(one_way_slippage, two),
        )

    def one_way_cost(
        self, *, is_maker: bool = False, participation_of_adv: Decimal = Decimal(0)
    ) -> TradeCost:
        return TradeCost(
            fee_bps=self.fees.rate_bps(is_maker=is_maker),
            slippage_bps=self.slippage.slippage_bps(participation_of_adv=participation_of_adv),
        )

    @property
    def optimism_warnings(self) -> list[str]:
        """Assumptions that make results look better than reality is likely to be.

        Surfaced on the result rather than hidden in configuration, because the reader of a
        performance figure is the one who needs to know.
        """
        warnings: list[str] = []
        if self.latency.is_zero:
            warnings.append(
                "zero_latency: fills occur at the price that triggered the decision, which no "
                "live system achieves"
            )
        if self.liquidity.is_optimistic:
            warnings.append(
                "always_maker: assumes every resting order is hit, earning maker rates on all fills"
            )
        if self.fees.maker_bps < 0 and self.liquidity.is_optimistic:
            warnings.append(
                "rebate_dependent: results depend on earning a maker rebate on every fill"
            )
        if self.slippage.spread_crossing_bps == 0:
            warnings.append("no_spread_crossing: assumes fills at the mid rather than at the touch")
        if not self.partial_fills_enabled:
            warnings.append("no_partial_fills: assumes every order fills in full")
        return warnings

    @property
    def is_conservative(self) -> bool:
        return not self.optimism_warnings
