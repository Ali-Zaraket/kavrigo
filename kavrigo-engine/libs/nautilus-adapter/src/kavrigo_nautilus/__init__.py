"""NautilusTrader adapter.

The only Kavrigo package that imports a NautilusTrader symbol (ADR 0012). Everything else works
against the contracts in ``kavrigo_backtest``, so the engine stays replaceable.
"""

from __future__ import annotations

from kavrigo_nautilus.engine import ENGINE_NAME, NautilusBacktestAdapter
from kavrigo_nautilus.translation import (
    NANOS_PER_MILLI,
    bps_to_rate,
    to_nautilus_aggressor,
    to_nautilus_fill_model,
    to_nautilus_latency_model,
)

__version__ = "0.1.0"

__all__ = [
    "ENGINE_NAME",
    "NANOS_PER_MILLI",
    "NautilusBacktestAdapter",
    "__version__",
    "bps_to_rate",
    "to_nautilus_aggressor",
    "to_nautilus_fill_model",
    "to_nautilus_latency_model",
]
