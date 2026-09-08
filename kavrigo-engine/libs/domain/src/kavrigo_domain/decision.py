"""The decision contract (``MASTER_BUILD_SPEC.md`` §10).

An agent does not call an exchange. It returns a structured ``AgentDecision`` containing a
*proposed* action, the evidence for and against it, and an explicit statement of uncertainty.
Execution never depends on unconstrained prose (``AGENTS.md`` domain rule 1).

``UNKNOWN`` and ``NO_TRADE`` are first-class successful outcomes (domain rule 4). An agent that
cannot say "I don't know" will manufacture a view from noise.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from kavrigo_domain.base import DomainModel, UtcDatetime
from kavrigo_domain.identifiers import (
    AgentId,
    AgentVersionId,
    DecisionId,
    EvidenceId,
    InstrumentId,
    SnapshotId,
    WorkspaceId,
)
from kavrigo_domain.money import ExactDecimal, Money
from kavrigo_domain.snapshot import MarketRegime

__all__ = [
    "AgentDecision",
    "DecisionProposal",
    "DecisionState",
    "ModelCallRecord",
    "Prediction",
    "ProposedAction",
    "SignalScores",
]


class DecisionState(StrEnum):
    """The agent's read of the situation (``MASTER_BUILD_SPEC.md`` §6.7)."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    HIGH_RISK = "high_risk"
    UNKNOWN = "unknown"


class ProposedAction(StrEnum):
    """The only actions a model may propose (``MASTER_BUILD_SPEC.md`` §6.6).

    This is a closed set on purpose. A model cannot propose "withdraw", "transfer", "change
    risk policy", or any free-form instruction, because those words have no representation here.
    """

    BUY = "buy"
    SELL = "sell"
    REDUCE = "reduce"
    CLOSE = "close"
    HOLD = "hold"
    NO_TRADE = "no_trade"

    @property
    def requires_order(self) -> bool:
        return self in {
            ProposedAction.BUY,
            ProposedAction.SELL,
            ProposedAction.REDUCE,
            ProposedAction.CLOSE,
        }


class SignalScores(DomainModel):
    """Per-family signal contributions, each in [-1, 1].

    Signal families rather than raw indicators: dumping hundreds of indicators into a model
    produces confident noise (``MASTER_BUILD_SPEC.md`` §7).
    """

    price: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    order_flow: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    derivatives: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    liquidity: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    onchain: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    tokenomics: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    defi: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    events: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    news: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    macro: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0


class Prediction(DomainModel):
    """A quantified expectation with explicit uncertainty."""

    expected_return_bps: Annotated[int, Field(ge=-10_000, le=10_000)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    uncertainty: Annotated[float, Field(ge=0.0, le=1.0)]
    horizon_minutes: Annotated[int, Field(ge=1, le=100_800)]

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.confidence + self.uncertainty > 1.000_001:
            raise ValueError("confidence and uncertainty cannot jointly exceed 1.0")
        return self


class ModelCallRecord(DomainModel):
    """What the model gateway actually did, for cost accounting and reproducibility.

    ``resolved_model_identifier`` is recorded rather than the profile alone: a routing fallback
    must never silently change which model produced a reproducible result (ADR 0010).
    """

    model_call_id: Annotated[str, Field(pattern=r"^mc_[0-9a-f]{32}$")]
    profile: Annotated[str, Field(min_length=1, max_length=32)]
    resolved_model_identifier: Annotated[str, Field(min_length=1, max_length=128)]
    prompt_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    input_tokens: Annotated[int, Field(ge=0)]
    output_tokens: Annotated[int, Field(ge=0)]
    cost: Money
    latency_ms: Annotated[int, Field(ge=0)]
    tool_calls: Annotated[int, Field(ge=0)] = 0
    schema_validation_failed: bool = False
    trace_id: Annotated[str | None, Field(default=None, max_length=64)] = None
    # Additive fields: historical records remain readable. Gateway-produced records populate
    # these from trusted call context, never from model-generated JSON.
    workspace_id: WorkspaceId | None = None
    agent_id: AgentId | None = None
    agent_version_id: AgentVersionId | None = None
    decision_id: DecisionId | None = None
    request_hash: Annotated[str | None, Field(pattern=r"^sha256:[0-9a-f]{64}$")] = None
    output_hash: Annotated[str | None, Field(pattern=r"^sha256:[0-9a-f]{64}$")] = None
    schema_hash: Annotated[str | None, Field(pattern=r"^sha256:[0-9a-f]{64}$")] = None
    route_hash: Annotated[str | None, Field(pattern=r"^sha256:[0-9a-f]{64}$")] = None
    outcome: Annotated[str, Field(pattern=r"^[a-z_]{1,48}$")] = "success"
    usage_known: bool = True
    cost_is_reservation: bool = False
    """True when no reliable usage returned: this is a retained upper bound, not an invoice."""

    @model_validator(mode="after")
    def _validate_cost(self) -> Self:
        if self.cost.currency != "USD" or self.cost.amount < 0:
            raise ValueError("model call cost must be non-negative USD")
        if self.cost_is_reservation and self.usage_known:
            raise ValueError("reserved cost cannot claim known usage")
        return self


class DecisionProposal(DomainModel):
    """The model-owned part of a decision: no identity, timestamps, audit or call records.

    The decision is a *proposal*. Whether anything happens is determined by the portfolio layer
    and the deterministic risk engine, which the model cannot influence at runtime (ADR 0004).
    """

    market_regime: MarketRegime
    state: DecisionState
    signals: SignalScores
    prediction: Prediction
    proposed_action: ProposedAction
    proposed_notional: Money | None = None
    rationale: Annotated[str, Field(max_length=4000)] = ""
    """A concise structured rationale for the user. Never hidden chain-of-thought
    (``MASTER_BUILD_SPEC.md`` §29)."""

    evidence_refs: Annotated[list[EvidenceId], Field(max_length=256)] = []
    contradicting_evidence_refs: Annotated[list[EvidenceId], Field(max_length=256)] = []
    risk_flags: Annotated[list[str], Field(max_length=32)] = []
    reason_codes: Annotated[list[str], Field(max_length=32)] = []
    estimated_cost_bps: Annotated[ExactDecimal | None, Field(default=None)] = None
    """Estimated round-trip cost in basis points: fees plus expected slippage. The risk engine
    rejects when estimated edge does not exceed this plus a safety margin (§11.1)."""

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.proposed_action.requires_order:
            if self.proposed_notional is None or self.proposed_notional.is_zero:
                raise ValueError(
                    f"action {self.proposed_action.value} requires a non-zero proposed notional"
                )
            if self.proposed_notional.is_negative:
                raise ValueError("proposed notional must be positive; direction is the action")
        elif self.proposed_notional is not None and not self.proposed_notional.is_zero:
            raise ValueError(
                f"action {self.proposed_action.value} must not carry a non-zero notional"
            )

        if self.state is DecisionState.UNKNOWN and self.proposed_action.requires_order:
            raise ValueError("an UNKNOWN state cannot propose a trade; abstain instead")

        overlap = set(self.evidence_refs) & set(self.contradicting_evidence_refs)
        if overlap:
            raise ValueError(
                f"evidence cannot be both supporting and contradicting: {sorted(overlap)}"
            )
        return self

    @property
    def is_abstention(self) -> bool:
        """``NO_TRADE`` and ``HOLD`` are successful outcomes, not failures."""
        return not self.proposed_action.requires_order


class AgentDecision(DecisionProposal):
    """A validated proposal bound to server-owned context by the agent runtime. Not an order."""

    decision_id: DecisionId
    workspace_id: WorkspaceId
    agent_version_id: AgentVersionId
    snapshot_id: SnapshotId
    instrument_id: InstrumentId
    decided_at: UtcDatetime
    model_calls: Annotated[list[ModelCallRecord], Field(max_length=64)] = []
