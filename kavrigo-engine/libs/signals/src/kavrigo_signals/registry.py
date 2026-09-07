"""Feature definitions and versioning.

``MASTER_BUILD_SPEC.md`` §39 is explicit: no standalone feature-store product in V1. Feature
definitions live in code with version identifiers, ClickHouse holds history, and S3/Parquet holds
frozen datasets.

Versioning is load-bearing rather than bookkeeping. §38 requires that a change to a feature
version create a new agent version, because a formula change means a backtest and a live run
would compute different inputs from the same configuration. Two safeguards:

* each feature carries its own ``version``, so one formula can change without invalidating the
  rest;
* the registry exposes a ``manifest_hash`` over every (name, version) pair, which a test pins.
  Changing a formula without bumping its version leaves the hash unchanged, so the *golden-value*
  tests are what catch that — the hash catches the complementary mistake of adding or removing a
  feature without noticing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum

from kavrigo_domain import content_hash

__all__ = [
    "FEATURE_SET_VERSION",
    "FeatureDefinition",
    "FeatureFamily",
    "FeatureRegistry",
    "FeatureValue",
]

FEATURE_SET_VERSION = "v1"
"""Pinned on every ``FeatureVector`` and every ``AgentVersion``. Bump on any formula change."""


class FeatureFamily(StrEnum):
    """Signal families from ``MASTER_BUILD_SPEC.md`` §7.

    Features are grouped into families rather than presented as a flat list of indicators,
    because the decision layer reasons about families — dumping hundreds of raw indicators into
    a model produces confident noise (§7).
    """

    PRICE = "price"
    VOLUME = "volume"
    VOLATILITY = "volatility"
    MICROSTRUCTURE = "microstructure"
    ORDER_FLOW = "order_flow"
    RELATIVE_STRENGTH = "relative_strength"


@dataclass(frozen=True, slots=True)
class FeatureValue:
    """One computed feature, or an explicit statement that it could not be computed.

    ``value is None`` is a first-class outcome with a ``reason``. A feature that cannot be
    computed must say so: substituting zero would be a specific, wrong claim, and downstream an
    unknown feature drives abstention while a fabricated zero drives a trade.
    """

    name: str
    value: Decimal | None
    reason: str | None = None

    @property
    def is_available(self) -> bool:
        return self.value is not None


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    """A named, versioned feature and what it needs to be computable."""

    name: str
    version: str
    family: FeatureFamily
    description: str
    lookback: timedelta | None = None
    """Minimum history the window must cover. ``None`` means point-in-time only."""

    min_observations: int = 1
    requires: tuple[str, ...] = ()
    """Which event kinds this feature reads: ``trades``, ``quotes``, ``candles``."""

    unit: str = "ratio"

    @property
    def qualified_name(self) -> str:
        """``name@version`` — what gets recorded, so a stored value is self-describing."""
        return f"{self.name}@{self.version}"


class FeatureRegistry:
    """The set of features a feature-set version computes."""

    def __init__(self, definitions: Iterable[FeatureDefinition]) -> None:
        self._definitions: dict[str, FeatureDefinition] = {}
        for definition in definitions:
            if definition.name in self._definitions:
                raise ValueError(f"duplicate feature definition: {definition.name}")
            self._definitions[definition.name] = definition

    def __len__(self) -> int:
        return len(self._definitions)

    def __contains__(self, name: object) -> bool:
        return name in self._definitions

    def get(self, name: str) -> FeatureDefinition | None:
        return self._definitions.get(name)

    @property
    def definitions(self) -> list[FeatureDefinition]:
        return sorted(self._definitions.values(), key=lambda d: d.name)

    def by_family(self, family: FeatureFamily) -> list[FeatureDefinition]:
        return [d for d in self.definitions if d.family is family]

    @property
    def manifest(self) -> list[dict[str, str]]:
        """The stable description of this feature set, for the reproducibility bundle."""
        return [
            {
                "name": d.name,
                "version": d.version,
                "family": d.family.value,
                "unit": d.unit,
            }
            for d in self.definitions
        ]

    @property
    def manifest_hash(self) -> str:
        """Content hash of the manifest.

        Recorded alongside every backtest so a run can state exactly which features existed
        (``MASTER_BUILD_SPEC.md`` §12.2). A pinned test on this value catches a feature being
        added or removed without a deliberate decision.
        """
        return content_hash({"feature_set_version": FEATURE_SET_VERSION, "features": self.manifest})


FeatureComputer = Callable[..., FeatureValue]
