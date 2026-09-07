"""Kavrigo market ingestion.

Consumes public venue WebSocket streams, normalizes them into domain events, tracks stream
health, and writes to the analytical store. Public data only: this service holds no exchange
credential and cannot reach a venue's trading endpoints (ADR 0017).
"""

from __future__ import annotations

from kavrigo_market_ingestion.envelopes import EVENT_TYPES, envelope_for, partition_key_for
from kavrigo_market_ingestion.pipeline import (
    IngestionPipeline,
    IngestionStats,
    PipelineConfig,
)
from kavrigo_market_ingestion.settings import VenueConfig, default_venues
from kavrigo_market_ingestion.sinks import (
    ClickHouseSink,
    EventSink,
    MemorySink,
    clickhouse_rows_for,
)

__version__ = "0.1.0"

__all__ = [
    "EVENT_TYPES",
    "ClickHouseSink",
    "EventSink",
    "IngestionPipeline",
    "IngestionStats",
    "MemorySink",
    "PipelineConfig",
    "VenueConfig",
    "__version__",
    "clickhouse_rows_for",
    "default_venues",
    "envelope_for",
    "partition_key_for",
]
