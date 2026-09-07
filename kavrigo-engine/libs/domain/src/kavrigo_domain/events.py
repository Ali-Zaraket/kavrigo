"""The canonical event envelope (``MASTER_BUILD_SPEC.md`` §18.1).

Every event on the bus carries the same envelope so that provenance, ordering and tenancy are
never provider-specific concerns. The Protobuf definition in
``kavrigo-engine/libs/data-contracts/proto/kavrigo/v1/envelope.proto`` is the wire contract;
this model is the in-process validation contract, and the two must stay in step.

Three timestamps are distinguished deliberately (``MASTER_BUILD_SPEC.md`` §8.5):

* ``event_time`` — when the thing happened at the source.
* ``ingested_at`` — when Kavrigo first saw it. Freshness and staleness are measured from here.
* ``provider_revision_time`` — when the provider last revised the record. Backtests must not
  silently consume a revised label as if it had been known at ``event_time``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import Field, model_validator

from kavrigo_domain.base import DomainModel, UtcDatetime
from kavrigo_domain.identifiers import WorkspaceId

__all__ = ["EventEnvelope", "EventSource", "SourceKind", "TenantScope"]


class SourceKind(StrEnum):
    """Where an event came from, which determines how much it may be trusted."""

    EXCHANGE_STREAM = "exchange_stream"
    EXCHANGE_REST = "exchange_rest"
    DATA_PROVIDER = "data_provider"
    ONCHAIN = "onchain"
    NEWS_FEED = "news_feed"
    MACRO_CALENDAR = "macro_calendar"
    MCP_TOOL = "mcp_tool"
    INTERNAL = "internal"
    SIMULATION = "simulation"

    @property
    def is_untrusted_content(self) -> bool:
        """Whether payloads from this source must pass the sanitisation pipeline (§14).

        News feeds and MCP tool output are attacker-influenced text. They are data, never
        instruction, and never reach a decision agent unstructured.
        """
        return self in {SourceKind.NEWS_FEED, SourceKind.MCP_TOOL}


class EventSource(DomainModel):
    """Provenance for a single event (``MASTER_BUILD_SPEC.md`` §8.4)."""

    kind: SourceKind
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    venue: Annotated[str | None, Field(default=None, max_length=32)] = None
    stream: Annotated[str | None, Field(default=None, max_length=128)] = None
    schema_version: Annotated[str, Field(pattern=r"^v?\d+(\.\d+)*$")] = "1"
    transform_version: Annotated[str | None, Field(default=None, max_length=32)] = None
    provider_sequence: int | None = None
    provider_revision_time: UtcDatetime | None = None
    is_revision: bool = False
    license_ref: Annotated[str | None, Field(default=None, max_length=128)] = None
    """Reference to the data-licence entry that permits using this record (§8.3)."""


class TenantScope(DomainModel):
    """Marks an event as private to one workspace.

    Public market data has no tenant scope. Decisions, orders and portfolio events do, and the
    partitioning and access rules follow from it (``MASTER_BUILD_SPEC.md`` §20).
    """

    workspace_id: WorkspaceId


class EventEnvelope(DomainModel):
    """Canonical envelope wrapping every payload published to the event bus."""

    event_id: Annotated[str, Field(min_length=1, max_length=64)]
    event_type: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+\.v\d+$")]
    """Dotted topic-style type ending in a version, e.g. ``market.trade.raw.v1``."""

    schema_version: Annotated[int, Field(ge=1)] = 1
    tenant_scope: TenantScope | None = None
    source: EventSource
    event_time: UtcDatetime
    ingested_at: UtcDatetime
    sequence: Annotated[int | None, Field(default=None, ge=0)] = None
    partition_key: Annotated[str, Field(min_length=1, max_length=128)]
    """Ordering is guaranteed only within this key (``MASTER_BUILD_SPEC.md`` §18.3)."""

    trace_id: Annotated[str | None, Field(default=None, max_length=64)] = None
    correlation_id: Annotated[str | None, Field(default=None, max_length=64)] = None
    payload: dict[str, Any]

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.ingested_at < self.event_time:
            # Tolerating this would let a clock-skewed provider produce negative data age and
            # defeat every staleness check downstream.
            raise ValueError(
                "ingested_at precedes event_time; check provider clock skew before publishing"
            )
        return self

    def age_ms_at(self, now: UtcDatetime) -> int:
        """Data age in milliseconds, measured from ``event_time``.

        Freshness is a risk input, not a display detail (``AGENTS.md`` domain rule 5).
        """
        return int((now - self.event_time).total_seconds() * 1000)
