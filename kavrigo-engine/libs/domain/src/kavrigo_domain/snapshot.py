"""Market snapshots: the frozen, point-in-time view a decision is computed from.

``MASTER_BUILD_SPEC.md`` §12.3 and §8.5. A snapshot is the answer to "what did the agent know,
and when did it know it". Everything a decision cycle reads comes from a snapshot; nothing reads
"latest" mid-cycle. That is what makes a decision reproducible and a backtest honest.

The data-quality score (§43) is a first-class field because the risk engine can require a
minimum: degraded or partially missing data is a reason to abstain, not to guess.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from kavrigo_domain.base import DomainModel, UtcDatetime
from kavrigo_domain.identifiers import EvidenceId, InstrumentId, SnapshotId
from kavrigo_domain.money import ExactDecimal

__all__ = [
    "DataFamily",
    "DataQuality",
    "FeatureVector",
    "FreshnessReport",
    "MarketRegime",
    "MarketSnapshot",
]


class DataFamily(StrEnum):
    """Data families that carry independent freshness budgets (``MASTER_BUILD_SPEC.md`` §11.3)."""

    TRADES = "trades"
    BOOK = "book"
    CANDLES = "candles"
    DERIVATIVES = "derivatives"
    ONCHAIN = "onchain"
    DEFI = "defi"
    NEWS = "news"
    MACRO = "macro"
    REFERENCE = "reference"


class MarketRegime(StrEnum):
    """Regime labels from ``MASTER_BUILD_SPEC.md`` §44.

    The label set is closed on purpose: a model may interpret regime context, but it may not
    invent unbounded regime labels during execution, because downstream policy keys off them.
    """

    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    HIGH_VOLATILITY = "high_volatility"
    LOW_LIQUIDITY = "low_liquidity"
    DELEVERAGING = "deleveraging"
    CROWDED_LONG = "crowded_long"
    CROWDED_SHORT = "crowded_short"
    EVENT_RISK = "event_risk"
    UNKNOWN = "unknown"


class FreshnessReport(DomainModel):
    """Observed data age per family at snapshot time."""

    age_ms: dict[DataFamily, int]
    stale_families: Annotated[list[DataFamily], Field(max_length=16)] = []
    missing_families: Annotated[list[DataFamily], Field(max_length=16)] = []

    @model_validator(mode="after")
    def _validate(self) -> Self:
        for family, age in self.age_ms.items():
            if age < 0:
                raise ValueError(f"negative data age for {family.value}; check clock skew")
        return self

    def age_for(self, family: DataFamily) -> int | None:
        return self.age_ms.get(family)


class DataQuality(DomainModel):
    """Snapshot quality score and its components (``MASTER_BUILD_SPEC.md`` §43)."""

    score: Annotated[float, Field(ge=0.0, le=1.0)]
    freshness: FreshnessReport
    provider_health_ok: bool = True
    sequence_complete: bool = True
    cross_provider_agreement: Annotated[float | None, Field(default=None, ge=0.0, le=1.0)] = None
    missing_feature_ratio: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    contains_revised_data: bool = False
    """True if any input was a provider revision. A backtest must treat this as a leakage flag
    unless the revision was known at ``as_of`` (``MASTER_BUILD_SPEC.md`` §8.5)."""

    notes: Annotated[list[str], Field(max_length=32)] = []


class FeatureVector(DomainModel):
    """Deterministic, versioned features for one instrument at snapshot time.

    Feature values are ``Decimal``: they feed sizing and threshold comparisons, and a float that
    rounds differently between the backtest and the live path is a reproducibility bug.
    """

    instrument_id: InstrumentId
    feature_set_version: Annotated[str, Field(pattern=r"^v\d+(\.\d+)*$")]
    values: dict[str, ExactDecimal]
    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class MarketSnapshot(DomainModel):
    """An immutable point-in-time view: features, evidence, regime and quality.

    ``as_of`` is the decision time. Nothing in a snapshot may carry information that was not
    available at ``as_of`` — that single rule is what separates a backtest from a fiction.
    """

    snapshot_id: SnapshotId
    as_of: UtcDatetime
    created_at: UtcDatetime
    instruments: Annotated[list[InstrumentId], Field(min_length=1, max_length=512)]
    features: Annotated[list[FeatureVector], Field(max_length=512)] = []
    evidence_refs: Annotated[list[EvidenceId], Field(max_length=512)] = []
    regime: MarketRegime = MarketRegime.UNKNOWN
    quality: DataQuality
    dataset_manifest_ref: Annotated[str | None, Field(default=None, max_length=256)] = None
    """Points at the frozen dataset manifest for backtests (``MASTER_BUILD_SPEC.md`` §12.2)."""

    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.created_at < self.as_of:
            raise ValueError("snapshot created_at precedes as_of")
        known = {i.value for i in self.instruments}
        for feature in self.features:
            if feature.instrument_id.value not in known:
                raise ValueError(
                    f"feature vector for {feature.instrument_id.value} is not in the snapshot "
                    "universe"
                )
        return self
