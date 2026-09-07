"""Property-based invariants for the feature engine (``MASTER_BUILD_SPEC.md`` §37).

The headline property is the first one: **no event that arrived after ``as_of`` can change any
feature value.** Example tests show that holds for the cases someone thought of; this asserts it
for every window Hypothesis can build. If it ever fails, every backtest the platform has run is
suspect, so it is worth stating as a property rather than a handful of examples.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from kavrigo_domain import AggressorSide, InstrumentId, MarketTrade, Price, Quantity
from kavrigo_signals import FeatureEngine, InstrumentWindow, MarketFrame, features

pytestmark = pytest.mark.property

AS_OF = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
BTC = InstrumentId.parse("BTC-USDT.BINANCE")
ETH = InstrumentId.parse("ETH-USDT.BINANCE")
_15M = timedelta(minutes=15)
_1H = timedelta(hours=1)

prices = st.decimals(min_value=Decimal("1"), max_value=Decimal("100000"), places=2)
quantities = st.decimals(min_value=Decimal("0.001"), max_value=Decimal("1000"), places=3)
minutes_ago = st.integers(min_value=0, max_value=180)
aggressors = st.sampled_from(list(AggressorSide))


@st.composite
def trades(draw: st.DrawFn, instrument: InstrumentId = BTC) -> MarketTrade:
    price = draw(prices)
    quantity = draw(quantities)
    ago = timedelta(minutes=draw(minutes_ago), seconds=draw(st.integers(0, 59)))
    venue_time = AS_OF - ago
    return MarketTrade(
        instrument_id=instrument,
        price=Price(value=price, base=instrument.base, quote=instrument.quote),
        quantity=Quantity(value=quantity, asset=instrument.base),
        aggressor=draw(aggressors),
        venue_time=venue_time,
        received_at=venue_time,
    )


@st.composite
def future_trades(draw: st.DrawFn) -> MarketTrade:
    """A trade the platform receives *after* the decision time."""
    ahead = timedelta(seconds=draw(st.integers(min_value=1, max_value=3600)))
    venue_time = AS_OF + ahead
    return MarketTrade(
        instrument_id=BTC,
        price=Price(value=draw(prices), base="BTC", quote="USDT"),
        quantity=Quantity(value=draw(quantities), asset="BTC"),
        aggressor=draw(aggressors),
        venue_time=venue_time,
        received_at=venue_time,
    )


class TestPointInTime:
    @given(
        history=st.lists(trades(), min_size=1, max_size=25),
        future=st.lists(future_trades(), min_size=1, max_size=10),
    )
    @settings(max_examples=150, deadline=None)
    def test_future_events_cannot_change_any_feature(
        self, history: list[MarketTrade], future: list[MarketTrade]
    ) -> None:
        """The invariant every backtest result depends on."""
        engine = FeatureEngine()

        without = FeatureEngine().compute_instrument(
            MarketFrame.of(AS_OF, [InstrumentWindow.build(BTC, AS_OF, trades=history)]),
            BTC.value,
        )
        with_future = engine.compute_instrument(
            MarketFrame.of(AS_OF, [InstrumentWindow.build(BTC, AS_OF, trades=[*history, *future])]),
            BTC.value,
        )
        assert without.values == with_future.values
        assert without.unavailable.keys() == with_future.unavailable.keys()

    @given(history=st.lists(trades(), min_size=1, max_size=20))
    @settings(max_examples=100, deadline=None)
    def test_event_order_does_not_change_the_result(self, history: list[MarketTrade]) -> None:
        """Windows sort by arrival, so the order events are handed in is irrelevant.

        Ingestion delivers out-of-order frames; if input order changed a feature, replaying a
        recording would not reproduce the original run.
        """
        engine = FeatureEngine()
        forward = engine.compute_instrument(
            MarketFrame.of(AS_OF, [InstrumentWindow.build(BTC, AS_OF, trades=history)]),
            BTC.value,
        )
        reversed_ = engine.compute_instrument(
            MarketFrame.of(
                AS_OF, [InstrumentWindow.build(BTC, AS_OF, trades=list(reversed(history)))]
            ),
            BTC.value,
        )
        assert forward.values == reversed_.values


class TestBoundedFeatures:
    @given(history=st.lists(trades(), min_size=1, max_size=30))
    @settings(max_examples=150, deadline=None)
    def test_taker_buy_ratio_stays_in_the_unit_interval(self, history: list[MarketTrade]) -> None:
        window = InstrumentWindow.build(BTC, AS_OF, trades=history)
        result = features.taker_buy_ratio(window, _15M, "r")
        if result.value is not None:
            assert Decimal(0) <= result.value <= Decimal(1)

    @given(
        bid_size=quantities,
        ask_size=quantities,
        bid=st.decimals(min_value=Decimal("1"), max_value=Decimal("1000"), places=2),
    )
    @settings(max_examples=150, deadline=None)
    def test_book_imbalance_stays_in_minus_one_to_one(
        self, bid_size: Decimal, ask_size: Decimal, bid: Decimal
    ) -> None:
        from kavrigo_domain import BookTicker

        quote = BookTicker(
            instrument_id=BTC,
            bid_price=Price(value=bid, base="BTC", quote="USDT"),
            bid_size=Quantity(value=bid_size, asset="BTC"),
            ask_price=Price(value=bid + Decimal("0.01"), base="BTC", quote="USDT"),
            ask_size=Quantity(value=ask_size, asset="BTC"),
            venue_time=AS_OF,
            received_at=AS_OF,
        )
        window = InstrumentWindow.build(BTC, AS_OF, quotes=[quote])
        result = features.book_imbalance(window, "i")
        assert result.value is not None
        assert Decimal(-1) <= result.value <= Decimal(1)

    @given(
        bid=st.decimals(min_value=Decimal("1"), max_value=Decimal("100000"), places=2),
        spread=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("100"), places=2),
    )
    @settings(max_examples=150, deadline=None)
    def test_spread_in_bps_is_always_positive(self, bid: Decimal, spread: Decimal) -> None:
        from kavrigo_domain import BookTicker

        quote = BookTicker(
            instrument_id=BTC,
            bid_price=Price(value=bid, base="BTC", quote="USDT"),
            bid_size=Quantity(value=Decimal(1), asset="BTC"),
            ask_price=Price(value=bid + spread, base="BTC", quote="USDT"),
            ask_size=Quantity(value=Decimal(1), asset="BTC"),
            venue_time=AS_OF,
            received_at=AS_OF,
        )
        window = InstrumentWindow.build(BTC, AS_OF, quotes=[quote])
        result = features.spread_bps(window, "s")
        assert result.value is not None
        assert result.value > 0


class TestRelativeStrength:
    @given(
        asset=st.lists(trades(instrument=ETH), min_size=2, max_size=15),
        benchmark=st.lists(trades(), min_size=2, max_size=15),
    )
    @settings(max_examples=100, deadline=None)
    def test_it_is_antisymmetric(
        self, asset: list[MarketTrade], benchmark: list[MarketTrade]
    ) -> None:
        """rs(a, b) == -rs(b, a). If it were not, "outperformance" would depend on which asset
        you happened to name first."""
        frame = MarketFrame.of(
            AS_OF,
            [
                InstrumentWindow.build(ETH, AS_OF, trades=asset),
                InstrumentWindow.build(BTC, AS_OF, trades=benchmark),
            ],
        )
        forward = features.relative_strength(frame, ETH.value, BTC.value, _1H, "rs")
        backward = features.relative_strength(frame, BTC.value, ETH.value, _1H, "rs")
        assume(forward.value is not None)
        assume(backward.value is not None)
        assert forward.value == -backward.value  # type: ignore[operator]

    @given(history=st.lists(trades(), min_size=2, max_size=15))
    @settings(max_examples=100, deadline=None)
    def test_an_asset_never_outperforms_itself(self, history: list[MarketTrade]) -> None:
        frame = MarketFrame.of(AS_OF, [InstrumentWindow.build(BTC, AS_OF, trades=history)])
        assert features.relative_strength(frame, BTC.value, BTC.value, _1H, "rs").value is None


class TestDeterminism:
    @given(history=st.lists(trades(), min_size=1, max_size=25))
    @settings(max_examples=100, deadline=None)
    def test_recomputation_is_bit_identical(self, history: list[MarketTrade]) -> None:
        frame = MarketFrame.of(AS_OF, [InstrumentWindow.build(BTC, AS_OF, trades=history)])
        engine = FeatureEngine()
        first = engine.compute_instrument(frame, BTC.value).to_vector()
        second = engine.compute_instrument(frame, BTC.value).to_vector()
        assert first.content_hash == second.content_hash

    @given(history=st.lists(trades(), min_size=1, max_size=25))
    @settings(max_examples=100, deadline=None)
    def test_every_reported_feature_is_registered(self, history: list[MarketTrade]) -> None:
        from kavrigo_signals import DEFAULT_REGISTRY

        frame = MarketFrame.of(AS_OF, [InstrumentWindow.build(BTC, AS_OF, trades=history)])
        result = FeatureEngine().compute_instrument(frame, BTC.value)
        for name in (*result.values, *result.unavailable):
            assert name in DEFAULT_REGISTRY
