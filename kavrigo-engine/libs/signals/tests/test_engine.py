"""The feature engine end to end: versioning, availability reporting and reproducibility."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from kavrigo_domain import AggressorSide, FeatureVector, content_hash
from kavrigo_signals import (
    DEFAULT_REGISTRY,
    FEATURE_SET_VERSION,
    FeatureEngine,
    FeatureFamily,
    FeatureRegistry,
    InstrumentWindow,
    MarketFrame,
)

from .conftest import AS_OF, BTC, ETH, quote, trade


def _rich_window(instrument=BTC):  # type: ignore[no-untyped-def]
    """A window with enough history and variety for most of the feature set."""
    trades = [
        trade(price="100", ago=timedelta(minutes=61), instrument=instrument),
        *[
            trade(
                price=str(100 + i),
                quantity="1",
                ago=timedelta(minutes=5 * i + 1),
                aggressor=AggressorSide.BUY if i % 2 == 0 else AggressorSide.SELL,
                instrument=instrument,
            )
            for i in range(12)
        ],
    ]
    quotes = [quote(bid="99.95", ask="100.05", instrument=instrument)]
    return InstrumentWindow.build(instrument, AS_OF, trades=trades, quotes=quotes)


@pytest.fixture
def frame() -> MarketFrame:
    return MarketFrame.of(AS_OF, [_rich_window(BTC), _rich_window(ETH)])


class TestRegistry:
    def test_the_required_families_are_all_covered(self) -> None:
        """``AGENTS.md`` step 6: returns, volume, volatility, spread, book imbalance,
        relative strength."""
        for family in FeatureFamily:
            assert DEFAULT_REGISTRY.by_family(family), f"no features in {family.value}"

    def test_every_feature_is_versioned(self) -> None:
        for definition in DEFAULT_REGISTRY.definitions:
            assert definition.version
            assert definition.qualified_name.endswith(f"@{definition.version}")

    def test_the_manifest_hash_is_pinned(self) -> None:
        """A change here means a feature was added, removed or renamed.

        That is a new feature-set version and therefore a new agent version
        (``MASTER_BUILD_SPEC.md`` §38) — so this failing is a prompt to make that decision
        deliberately, not to update the constant reflexively.
        """
        assert DEFAULT_REGISTRY.manifest_hash == (
            "sha256:2023c18ceb866bf16b1cea0037a03848bb3c39109c356d4c3707b8baa03b1cc8"
        )

    def test_the_manifest_hash_changes_when_the_set_changes(self) -> None:
        reduced = FeatureRegistry(DEFAULT_REGISTRY.definitions[:-1])
        assert reduced.manifest_hash != DEFAULT_REGISTRY.manifest_hash

    def test_duplicate_definitions_are_refused(self) -> None:
        definition = DEFAULT_REGISTRY.definitions[0]
        with pytest.raises(ValueError, match="duplicate feature definition"):
            FeatureRegistry([definition, definition])


class TestComputation:
    def test_a_rich_window_computes_most_of_the_set(self, frame: MarketFrame) -> None:
        engine = FeatureEngine(benchmark=BTC)
        result = engine.compute_instrument(frame, ETH.value)
        assert result.availability > 0.8
        assert "return_1h" in result.values
        assert "spread_bps" in result.values
        assert "book_imbalance" in result.values
        assert "relative_strength_1h" in result.values

    def test_computing_the_whole_frame(self, frame: MarketFrame) -> None:
        results = FeatureEngine(benchmark=BTC).compute_frame(frame)
        assert set(results) == {BTC.value, ETH.value}

    def test_an_unknown_instrument_raises(self, frame: MarketFrame) -> None:
        with pytest.raises(KeyError, match="no window"):
            FeatureEngine().compute_instrument(frame, "SOL-USDT.BINANCE")


class TestAvailabilityReporting:
    def test_missing_features_are_reported_with_a_reason_not_defaulted(self) -> None:
        """A fabricated zero drives a trade; a stated absence drives abstention."""
        empty = MarketFrame.of(AS_OF, [InstrumentWindow.build(BTC, AS_OF)])
        result = FeatureEngine().compute_instrument(empty, BTC.value)
        assert result.values == {}
        assert result.availability == 0.0
        assert "return_1h" in result.unavailable
        assert result.unavailable["spread_bps"] == "no quote in window"

    def test_a_quoteless_window_still_computes_price_features(self) -> None:
        window = InstrumentWindow.build(
            BTC,
            AS_OF,
            trades=[
                trade(price="100", ago=timedelta(minutes=61)),
                trade(price="110", ago=timedelta(minutes=1)),
            ],
        )
        result = FeatureEngine().compute_instrument(MarketFrame.of(AS_OF, [window]), BTC.value)
        assert result.values["return_1h"] == Decimal("0.1")
        assert "spread_bps" in result.unavailable

    def test_availability_is_a_fraction_of_the_whole_set(self, frame: MarketFrame) -> None:
        result = FeatureEngine(benchmark=BTC).compute_instrument(frame, ETH.value)
        assert len(result.values) + len(result.unavailable) == len(DEFAULT_REGISTRY)
        assert 0.0 <= result.availability <= 1.0

    def test_relative_strength_needs_a_configured_benchmark(self, frame: MarketFrame) -> None:
        result = FeatureEngine().compute_instrument(frame, ETH.value)
        assert result.unavailable["relative_strength_1h"] == "no benchmark configured"


class TestReproducibility:
    def test_the_same_frame_yields_the_same_vector_hash(self, frame: MarketFrame) -> None:
        """The property the whole engine exists to provide: a decision can be replayed."""
        engine = FeatureEngine(benchmark=BTC)
        first = engine.compute_instrument(frame, ETH.value).to_vector()
        second = engine.compute_instrument(frame, ETH.value).to_vector()
        assert first.content_hash == second.content_hash

    def test_a_different_input_yields_a_different_hash(self, frame: MarketFrame) -> None:
        engine = FeatureEngine(benchmark=BTC)
        baseline = engine.compute_instrument(frame, ETH.value).to_vector()

        moved = MarketFrame.of(
            AS_OF,
            [
                _rich_window(BTC),
                InstrumentWindow.build(
                    ETH,
                    AS_OF,
                    trades=[
                        trade(price="100", ago=timedelta(minutes=61), instrument=ETH),
                        trade(price="200", ago=timedelta(minutes=1), instrument=ETH),
                    ],
                ),
            ],
        )
        changed = engine.compute_instrument(moved, ETH.value).to_vector()
        assert changed.content_hash != baseline.content_hash

    def test_the_vector_carries_the_feature_set_version(self, frame: MarketFrame) -> None:
        vector = FeatureEngine(benchmark=BTC).compute_instrument(frame, ETH.value).to_vector()
        assert isinstance(vector, FeatureVector)
        assert vector.feature_set_version == FEATURE_SET_VERSION

    def test_the_hash_covers_the_version_not_just_the_values(self, frame: MarketFrame) -> None:
        """Two runs with identical numbers under different formula versions must not collide."""
        values = FeatureEngine(benchmark=BTC).compute_instrument(frame, ETH.value).values
        v1 = content_hash(
            {"instrument_id": ETH.value, "feature_set_version": "v1", "values": values}
        )
        v2 = content_hash(
            {"instrument_id": ETH.value, "feature_set_version": "v2", "values": values}
        )
        assert v1 != v2

    def test_every_value_is_decimal(self, frame: MarketFrame) -> None:
        result = FeatureEngine(benchmark=BTC).compute_instrument(frame, ETH.value)
        assert all(isinstance(v, Decimal) for v in result.values.values())
