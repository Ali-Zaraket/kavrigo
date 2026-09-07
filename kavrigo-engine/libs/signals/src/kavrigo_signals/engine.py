"""The feature engine: a market frame in, versioned feature vectors out.

The engine's contract is narrow and total: given a :class:`MarketFrame`, it produces one
:class:`kavrigo_domain.FeatureVector` per instrument, containing every feature that could be
computed, plus an explicit record of the ones that could not and why.

That second half matters as much as the first. A decision cycle needs to know *which* features
were unavailable — an agent reasoning about an instrument with no quote and no volatility
estimate should abstain, and it can only do that if the absence is visible rather than papered
over with zeros.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from kavrigo_domain import FeatureVector, InstrumentId, content_hash
from kavrigo_signals import features
from kavrigo_signals.registry import (
    FEATURE_SET_VERSION,
    FeatureDefinition,
    FeatureFamily,
    FeatureRegistry,
    FeatureValue,
)
from kavrigo_signals.window import InstrumentWindow, MarketFrame

__all__ = ["DEFAULT_REGISTRY", "FeatureEngine", "InstrumentFeatures"]

_5M = timedelta(minutes=5)
_15M = timedelta(minutes=15)
_1H = timedelta(hours=1)


def _definition(
    name: str,
    family: FeatureFamily,
    description: str,
    *,
    lookback: timedelta | None = None,
    requires: tuple[str, ...] = ("trades",),
    unit: str = "ratio",
    min_observations: int = 1,
) -> FeatureDefinition:
    return FeatureDefinition(
        name=name,
        # Every feature starts at v1. Bump only the one whose formula changed, so an unrelated
        # feature's history stays comparable across the change (MASTER_BUILD_SPEC.md 38).
        version="v1",
        family=family,
        description=description,
        lookback=lookback,
        min_observations=min_observations,
        requires=requires,
        unit=unit,
    )


#: The V1 feature set. Covers exactly what ``AGENTS.md`` step 6 requires — returns, volume,
#: volatility, spread, order-book imbalance and relative strength — plus VWAP and the order-flow
#: pair, which ``MASTER_BUILD_SPEC.md`` §7.1/§7.2 call for and which fall out of the same data.
DEFAULT_REGISTRY = FeatureRegistry(
    [
        _definition(
            "return_5m",
            FeatureFamily.PRICE,
            "Fractional price change over 5 minutes.",
            lookback=_5M,
        ),
        _definition(
            "return_15m",
            FeatureFamily.PRICE,
            "Fractional price change over 15 minutes.",
            lookback=_15M,
        ),
        _definition(
            "return_1h", FeatureFamily.PRICE, "Fractional price change over 1 hour.", lookback=_1H
        ),
        _definition(
            "vwap_15m",
            FeatureFamily.PRICE,
            "Volume-weighted average price over 15 minutes.",
            lookback=_15M,
            unit="quote_currency",
        ),
        _definition(
            "volume_15m",
            FeatureFamily.VOLUME,
            "Base-asset volume traded over 15 minutes.",
            lookback=_15M,
            unit="base_asset",
        ),
        _definition(
            "volume_zscore_1h",
            FeatureFamily.VOLUME,
            "Standard deviations between the latest 5-minute bucket's volume and its 1-hour baseline.",
            lookback=_1H,
            min_observations=4,
            unit="zscore",
        ),
        _definition(
            "realized_volatility_15m",
            FeatureFamily.VOLATILITY,
            "Standard deviation of consecutive log returns over 15 minutes. Not annualised.",
            lookback=_15M,
            min_observations=3,
        ),
        _definition(
            "realized_volatility_1h",
            FeatureFamily.VOLATILITY,
            "Standard deviation of consecutive log returns over 1 hour. Not annualised.",
            lookback=_1H,
            min_observations=3,
        ),
        _definition(
            "spread_bps",
            FeatureFamily.MICROSTRUCTURE,
            "Bid-ask spread of the latest quote, in basis points of the mid.",
            requires=("quotes",),
            unit="bps",
        ),
        _definition(
            "book_imbalance",
            FeatureFamily.MICROSTRUCTURE,
            "Top-of-book size imbalance in [-1, 1]; positive means more bid than ask size.",
            requires=("quotes",),
        ),
        _definition(
            "cvd_15m",
            FeatureFamily.ORDER_FLOW,
            "Cumulative volume delta over 15 minutes: taker buys minus taker sells.",
            lookback=_15M,
            unit="base_asset",
        ),
        _definition(
            "taker_buy_ratio_15m",
            FeatureFamily.ORDER_FLOW,
            "Share of attributed volume that was taker buying, over 15 minutes.",
            lookback=_15M,
        ),
        _definition(
            "relative_strength_1h",
            FeatureFamily.RELATIVE_STRENGTH,
            "1-hour return minus the benchmark's 1-hour return.",
            lookback=_1H,
        ),
    ]
)


@dataclass(frozen=True, slots=True)
class InstrumentFeatures:
    """Computed features for one instrument, available and unavailable alike."""

    instrument_id: InstrumentId
    values: dict[str, Decimal]
    unavailable: dict[str, str] = field(default_factory=dict)

    @property
    def availability(self) -> float:
        """Share of the feature set that could be computed, in [0, 1].

        Feeds the snapshot's ``missing_feature_ratio`` (``MASTER_BUILD_SPEC.md`` §43), which the
        risk engine can require a minimum of.
        """
        total = len(self.values) + len(self.unavailable)
        return len(self.values) / total if total else 0.0

    def to_vector(self) -> FeatureVector:
        """The domain contract, content-hashed so a decision can be replayed against it."""
        return FeatureVector(
            instrument_id=self.instrument_id,
            feature_set_version=FEATURE_SET_VERSION,
            values=self.values,
            content_hash=content_hash(
                {
                    "instrument_id": self.instrument_id.value,
                    "feature_set_version": FEATURE_SET_VERSION,
                    "values": self.values,
                }
            ),
        )


class FeatureEngine:
    """Computes the registered feature set over a market frame."""

    def __init__(
        self,
        registry: FeatureRegistry = DEFAULT_REGISTRY,
        *,
        benchmark: InstrumentId | str | None = None,
    ) -> None:
        self._registry = registry
        self._benchmark = benchmark.value if isinstance(benchmark, InstrumentId) else benchmark

    @property
    def registry(self) -> FeatureRegistry:
        return self._registry

    @property
    def feature_set_version(self) -> str:
        return FEATURE_SET_VERSION

    def compute_frame(self, frame: MarketFrame) -> dict[str, InstrumentFeatures]:
        """Compute every instrument in the frame, keyed by canonical instrument id."""
        return {key: self.compute_instrument(frame, key) for key in frame.windows}

    def compute_instrument(self, frame: MarketFrame, instrument_key: str) -> InstrumentFeatures:
        window = frame.window_for(instrument_key)
        if window is None:
            raise KeyError(f"no window for {instrument_key} in frame")

        results = [
            *self._price_features(window),
            *self._volume_features(window),
            *self._volatility_features(window),
            *self._microstructure_features(window),
            *self._order_flow_features(window),
            self._relative_strength(frame, instrument_key),
        ]

        values: dict[str, Decimal] = {}
        unavailable: dict[str, str] = {}
        for result in results:
            # A feature not in the registry would be recorded under a name nothing can explain,
            # so it is treated as a programming error rather than silently accepted.
            if result.name not in self._registry:
                raise KeyError(f"computed unregistered feature {result.name!r}")
            if result.value is None:
                unavailable[result.name] = result.reason or "unavailable"
            else:
                values[result.name] = result.value

        return InstrumentFeatures(
            instrument_id=window.instrument_id, values=values, unavailable=unavailable
        )

    # ---------------------------------------------------------------- families

    def _price_features(self, window: InstrumentWindow) -> list[FeatureValue]:
        return [
            features.simple_return(window, _5M, "return_5m"),
            features.simple_return(window, _15M, "return_15m"),
            features.simple_return(window, _1H, "return_1h"),
            features.vwap(window, _15M, "vwap_15m"),
        ]

    def _volume_features(self, window: InstrumentWindow) -> list[FeatureValue]:
        return [
            features.traded_volume(window, _15M, "volume_15m"),
            features.volume_zscore(window, _1H, _5M, "volume_zscore_1h"),
        ]

    def _volatility_features(self, window: InstrumentWindow) -> list[FeatureValue]:
        return [
            features.realized_volatility(window, _15M, "realized_volatility_15m"),
            features.realized_volatility(window, _1H, "realized_volatility_1h"),
        ]

    def _microstructure_features(self, window: InstrumentWindow) -> list[FeatureValue]:
        return [
            features.spread_bps(window, "spread_bps"),
            features.book_imbalance(window, "book_imbalance"),
        ]

    def _order_flow_features(self, window: InstrumentWindow) -> list[FeatureValue]:
        return [
            features.cumulative_volume_delta(window, _15M, "cvd_15m"),
            features.taker_buy_ratio(window, _15M, "taker_buy_ratio_15m"),
        ]

    def _relative_strength(self, frame: MarketFrame, instrument_key: str) -> FeatureValue:
        name = "relative_strength_1h"
        if self._benchmark is None:
            return FeatureValue(name=name, value=None, reason="no benchmark configured")
        return features.relative_strength(frame, instrument_key, self._benchmark, _1H, name)
