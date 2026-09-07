"""Kavrigo feature engine.

Deterministic, versioned, point-in-time features (``AGENTS.md`` step 6). Three properties hold
throughout, and each is enforced rather than intended:

* **Deterministic** — decimal arithmetic in a fixed context, so a backtest and a live run
  compute identical values from identical inputs.
* **Versioned** — every feature carries a version and the set carries a manifest hash, because a
  formula change means a new agent version (``MASTER_BUILD_SPEC.md`` §38).
* **Point-in-time** — a window contains only what was received by ``as_of``, measured by arrival
  rather than venue time, so the latency a live system suffers is not silently removed.

Unavailable features are reported with a reason instead of being defaulted to zero: absence
drives abstention, a fabricated zero drives a trade.
"""

from __future__ import annotations

from kavrigo_signals.engine import DEFAULT_REGISTRY, FeatureEngine, InstrumentFeatures
from kavrigo_signals.numeric import FEATURE_CONTEXT, mean, safe_divide, stdev, to_bps
from kavrigo_signals.registry import (
    FEATURE_SET_VERSION,
    FeatureDefinition,
    FeatureFamily,
    FeatureRegistry,
    FeatureValue,
)
from kavrigo_signals.window import InstrumentWindow, MarketFrame

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_REGISTRY",
    "FEATURE_CONTEXT",
    "FEATURE_SET_VERSION",
    "FeatureDefinition",
    "FeatureEngine",
    "FeatureFamily",
    "FeatureRegistry",
    "FeatureValue",
    "InstrumentFeatures",
    "InstrumentWindow",
    "MarketFrame",
    "__version__",
    "mean",
    "safe_divide",
    "stdev",
    "to_bps",
]
