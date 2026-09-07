"""Builders for backtest contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from kavrigo_backtest import (
    CostModel,
    DatasetManifest,
    DatasetSource,
    FeeSchedule,
    LatencyModel,
    SlippageModel,
    TimeBasis,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 2, 1, tzinfo=UTC)
HASH = "sha256:" + "ab" * 32


def oid(prefix: str, n: int = 1) -> str:
    return f"{prefix}_{n:032x}"


def source(**overrides: object) -> DatasetSource:
    values: dict[str, object] = {
        "provider": "binance",
        "venue": "BINANCE",
        "dataset": "kavrigo.market_trades",
        "row_count": 1_000_000,
        "content_hash": HASH,
        "first_event_time": START,
        "last_event_time": END - timedelta(minutes=1),
        "last_ingested_at": END - timedelta(seconds=30),
        "license_ref": "binance-public-tos",
    }
    values.update(overrides)
    return DatasetSource(**values)  # type: ignore[arg-type]


def manifest(**overrides: object) -> DatasetManifest:
    values: dict[str, object] = {
        "manifest_id": oid("ds"),
        "created_at": END,
        "period_start": START,
        "period_end": END,
        "time_basis": TimeBasis.INGESTED_AT,
        "sources": [source()],
        "instruments": ["BTC-USDT.BINANCE", "ETH-USDT.BINANCE"],
        "feature_set_version": "v1",
    }
    values.update(overrides)
    return DatasetManifest(**values)  # type: ignore[arg-type]


def cost_model(**overrides: object) -> CostModel:
    values: dict[str, object] = {
        "fees": FeeSchedule(venue="BINANCE", maker_bps=Decimal("1"), taker_bps=Decimal("10")),
        "slippage": SlippageModel(spread_crossing_bps=Decimal("2")),
        "latency": LatencyModel(decision_to_venue_ms=50, venue_ack_ms=10, market_data_ms=20),
    }
    values.update(overrides)
    return CostModel(**values)  # type: ignore[arg-type]


@pytest.fixture
def default_manifest() -> DatasetManifest:
    return manifest()


@pytest.fixture
def default_costs() -> CostModel:
    return cost_model()
