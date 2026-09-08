"""Frozen runtime inputs and unapproved portfolio outputs (§6, §10, ADR 0024)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, model_validator

from kavrigo_domain import (
    AgentDecision,
    AgentVersion,
    DomainModel,
    EvidenceItem,
    FeatureVector,
    InstrumentId,
    MarketSnapshot,
    ModelCallRecord,
    Money,
    PortfolioSnapshot,
)
from kavrigo_domain.base import UtcDatetime
from kavrigo_domain.evidence import Score
from kavrigo_domain.identifiers import AgentVersionId, DecisionId, EvidenceId, WorkspaceId
from kavrigo_domain.money import ExactDecimal
from kavrigo_domain.risk import Percent
from kavrigo_domain.snapshot import MarketRegime
from kavrigo_model_gateway.contracts import Digest, Name


class ScannerPolicy(DomainModel):
    absolute_thresholds: dict[Name, Annotated[ExactDecimal, Field(gt=0)]]
    candidate_ttl_ms: Annotated[int, Field(strict=True, ge=1, le=3_600_000)]
    max_candidates: Annotated[int, Field(strict=True, ge=1, le=32)]

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if not 1 <= len(self.absolute_thresholds) <= 32:
            raise ValueError("scanner requires 1..32 explicit feature thresholds")
        return self


class Candidate(DomainModel):
    instrument_id: InstrumentId
    interest_score: Annotated[ExactDecimal, Field(ge=0, le=1)]
    reasons: tuple[Name, ...]
    expires_at: UtcDatetime


class NetworkContext(DomainModel):
    context_id: Name
    scope: Name
    instruments: Annotated[tuple[InstrumentId, ...], Field(min_length=1, max_length=256)]
    known_at: UtcDatetime
    valid_until: UtcDatetime
    health: Literal["normal", "degraded", "unknown"]
    liquidity_flow_score: Score
    activity_score: Score
    risk_score: Score
    evidence_refs: Annotated[tuple[EvidenceId, ...], Field(max_length=64)]
    content_hash: Digest

    @model_validator(mode="after")
    def _times(self) -> Self:
        if self.valid_until <= self.known_at:
            raise ValueError("network context must have a positive validity window")
        return self


class NetworkContextProvider(Protocol):
    def frozen_contexts(self) -> tuple[NetworkContext, ...]:
        """Return an already loaded snapshot once per cycle; no model-selected retrieval."""
        ...


class RuntimePolicy(DomainModel):
    version: Name
    code_version: Annotated[str, Field(min_length=1, max_length=128)]
    code_image_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    scanner: ScannerPolicy
    max_snapshot_age_ms: Annotated[int, Field(strict=True, ge=1, le=3_600_000)]
    max_portfolio_age_ms: Annotated[int, Field(strict=True, ge=1, le=3_600_000)]
    max_calls_per_cycle: Annotated[int, Field(strict=True, ge=1, le=32)]
    allocation_groups: dict[str, Name]
    max_new_allocation_pct: Percent
    max_group_exposure_pct: Percent
    fee_buffer_bps: Annotated[ExactDecimal, Field(ge=0, le=10_000)]
    """Explicit conservative cash buffer. Actual costs and limits are rechecked by risk."""


class RuntimeRegistration(DomainModel):
    agent_version: AgentVersion
    policy: RuntimePolicy
    pinned_model_identifier: Annotated[str | None, Field(min_length=1, max_length=128)] = None


class EvaluationRequest(DomainModel):
    workspace_id: WorkspaceId
    agent_version_id: AgentVersionId
    idempotency_key: Name
    horizon_minutes: Annotated[int, Field(strict=True, ge=1, le=100_800)]
    snapshot: MarketSnapshot
    portfolio: PortfolioSnapshot
    evidence: Annotated[tuple[EvidenceItem, ...], Field(max_length=512)]


class AnalysisInput(DomainModel):
    """Only frozen facts and policy constraints, never runtime IDs, tools or credentials."""

    instrument: InstrumentId
    as_of: UtcDatetime
    horizon_minutes: int
    market_regime: MarketRegime
    features: FeatureVector
    evidence: Annotated[tuple[EvidenceItem, ...], Field(max_length=64)]
    network: Annotated[tuple[NetworkContext, ...], Field(max_length=16)]
    available_cash: Money
    current_position_value: Money
    min_evidence_items: int
    require_contradicting_evidence: bool


class Allocation(DomainModel):
    """Inert proposal; cannot be passed to a broker. Step 11 must evaluate an OrderIntent."""

    decision_id: DecisionId
    instrument_id: InstrumentId
    requested_notional: Money
    allocated_notional: Money
    reason_codes: tuple[Name, ...]

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if self.requested_notional.currency != self.allocated_notional.currency:
            raise ValueError("allocation currencies must match")
        if not 0 <= self.allocated_notional.amount <= self.requested_notional.amount:
            raise ValueError("portfolio may only reduce a proposal")
        return self


class PortfolioDecision(DomainModel):
    portfolio_hash: Digest
    allocations: tuple[Allocation, ...]
    reason_codes: tuple[Name, ...] = ()


class EvaluationStatus(StrEnum):
    COMPLETED = "completed"
    REFUSED = "refused"
    IN_PROGRESS = "in_progress"


class EvaluationResult(DomainModel):
    status: EvaluationStatus
    workspace_id: WorkspaceId
    agent_version_id: AgentVersionId
    request_hash: Digest
    runtime_policy_hash: Digest
    reason_codes: tuple[Name, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    decisions: tuple[AgentDecision, ...] = ()
    portfolio_decision: PortfolioDecision | None = None
    network_contexts: tuple[NetworkContext, ...] = ()
    model_calls: tuple[ModelCallRecord, ...] = ()
