"""Translation between Kavrigo contracts and NautilusTrader types.

This module is the boundary ADR 0012 exists to create. Nothing outside this package imports a
Nautilus symbol, so replacing the engine is an adapter change rather than a rewrite.

Translation is where realism is either preserved or quietly lost, so the mappings that matter
are stated explicitly:

* **Fees** are basis points here and a decimal rate in Nautilus — a factor of 10,000 that is
  easy to get wrong and produces a backtest that looks 100x too cheap or too expensive.
* **Latency** is milliseconds here and nanoseconds in Nautilus.
* **Aggressor side** is the taker's side in both, but only because our adapters already
  normalised it; venues disagree, and this is where that normalisation has to hold.

Values verified against nautilus_trader 1.231.0 on 2026-09-07.
"""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.backtest.models import FillModel
from nautilus_trader.backtest.models import LatencyModel as NautilusLatencyModel
from nautilus_trader.model.enums import AggressorSide as NautilusAggressorSide

from kavrigo_backtest import CostModel, LatencyModel
from kavrigo_domain import AggressorSide

__all__ = [
    "NANOS_PER_MILLI",
    "bps_to_rate",
    "to_nautilus_aggressor",
    "to_nautilus_fill_model",
    "to_nautilus_latency_model",
]

NANOS_PER_MILLI = 1_000_000

_AGGRESSOR_MAP = {
    AggressorSide.BUY: NautilusAggressorSide.BUYER,
    AggressorSide.SELL: NautilusAggressorSide.SELLER,
    AggressorSide.UNKNOWN: NautilusAggressorSide.NO_AGGRESSOR,
}


def bps_to_rate(bps: Decimal) -> Decimal:
    """Basis points to a decimal rate: 10 bps becomes 0.001.

    The conversion every fee bug lives in. Kept as a named function with its own test rather
    than inlined at each call site.
    """
    return bps / Decimal(10_000)


def to_nautilus_aggressor(side: AggressorSide) -> NautilusAggressorSide:
    """Map our normalised taker side onto Nautilus's.

    Both are the *taker*. Our venue adapters already inverted Binance's ``m`` flag and
    Coinbase's maker-side ``side`` field, so the value arriving here is the aggressor; this
    mapping must not re-invert it.
    """
    return _AGGRESSOR_MAP[side]


def to_nautilus_latency_model(latency: LatencyModel) -> NautilusLatencyModel:
    """Milliseconds to nanoseconds.

    ``base_latency_nanos`` carries the decision-to-venue delay because that is the one that
    determines whether a fill happens at the price that triggered it. Nautilus defaults it to
    one full second, which would silently dominate any figure set elsewhere.

    **Nautilus composes these additively**: the effective insert latency it reports is
    ``base + insert``, verified against 1.231.0 on 2026-09-07. So passing ``venue_ack_ms`` as
    the insert leg yields ``decision_to_venue + venue_ack`` in total, which is what we want.
    Passing the already-summed total here instead would double-count the base leg and make every
    simulated order arrive later than the model says.
    """
    return NautilusLatencyModel(
        base_latency_nanos=latency.decision_to_venue_ms * NANOS_PER_MILLI,
        insert_latency_nanos=latency.venue_ack_ms * NANOS_PER_MILLI,
        update_latency_nanos=latency.venue_ack_ms * NANOS_PER_MILLI,
        cancel_latency_nanos=latency.venue_ack_ms * NANOS_PER_MILLI,
    )


def to_nautilus_fill_model(costs: CostModel, *, random_seed: int) -> FillModel:
    """Build the fill model, seeded so two runs of one configuration agree.

    ``prob_slippage`` is driven by whether the cost model expects to cross the spread at all: a
    model with zero spread crossing is asserting mid fills, and the fill model should not then
    add slippage on top of an assumption that already excluded it. The seed is pinned regardless
    (``MASTER_BUILD_SPEC.md`` §12.2) so a probabilistic model is still reproducible.
    """
    crosses_spread = costs.slippage.spread_crossing_bps > 0
    return FillModel(
        # A limit order resting at the touch is not guaranteed a fill in reality; 1.0 would be
        # the optimistic assumption. This stays configurable through the cost model as the
        # queue-position work in MASTER_BUILD_SPEC.md 12.4 lands.
        prob_fill_on_limit=1.0 if costs.liquidity.is_optimistic else 0.8,
        prob_slippage=0.5 if crosses_spread else 0.0,
        random_seed=random_seed,
    )
