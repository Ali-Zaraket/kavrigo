"""Kavrigo backtest contracts.

Engine-independent by design (ADR 0012): dataset manifests, cost models, evaluation metrics,
run configuration and the reproducibility bundle. The NautilusTrader implementation lives in
``kavrigo-nautilus-adapter`` and is the only package that imports a Nautilus symbol.
"""

from __future__ import annotations

from kavrigo_backtest.catalog import (
    BAR_PARQUET_SCHEMA,
    BarCatalog,
    LocalParquetBarCatalog,
    ParquetBarDatasetRef,
    parquet_bytes_hash,
)
from kavrigo_backtest.costs import (
    CostModel,
    FeeSchedule,
    LatencyModel,
    LiquidityAssumption,
    SlippageModel,
    TradeCost,
)
from kavrigo_backtest.fixture import (
    BacktestBar,
    InlineBarDataset,
    LongOnlyEmaStrategy,
    bar_dataset_hash,
)
from kavrigo_backtest.governance import ReferenceRiskReplay
from kavrigo_backtest.manifest import (
    DatasetManifest,
    DatasetSource,
    LeakageFinding,
    TimeBasis,
)
from kavrigo_backtest.metrics import (
    EquityPoint,
    PerformanceMetrics,
    TradeOutcome,
    compute_metrics,
)
from kavrigo_backtest.run import (
    BacktestEngine,
    BacktestResult,
    BacktestRunConfig,
    ReproducibilityBundle,
    RunStatus,
    cost_model_hash,
    refuse,
)

__version__ = "0.1.0"

__all__ = [
    "BAR_PARQUET_SCHEMA",
    "BacktestBar",
    "BacktestEngine",
    "BacktestResult",
    "BacktestRunConfig",
    "BarCatalog",
    "CostModel",
    "DatasetManifest",
    "DatasetSource",
    "EquityPoint",
    "FeeSchedule",
    "InlineBarDataset",
    "LatencyModel",
    "LeakageFinding",
    "LiquidityAssumption",
    "LocalParquetBarCatalog",
    "LongOnlyEmaStrategy",
    "ParquetBarDatasetRef",
    "PerformanceMetrics",
    "ReferenceRiskReplay",
    "ReproducibilityBundle",
    "RunStatus",
    "SlippageModel",
    "TimeBasis",
    "TradeCost",
    "TradeOutcome",
    "__version__",
    "bar_dataset_hash",
    "compute_metrics",
    "cost_model_hash",
    "parquet_bytes_hash",
    "refuse",
]
