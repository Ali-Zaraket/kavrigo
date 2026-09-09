"""Trusted risk registrations and frozen paper inputs; no model-selected policies (ADR 0004)."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from kavrigo_domain import (
    AgentDecision,
    AgentVersion,
    ApprovedOrderIntent,
    BookTicker,
    DomainModel,
    EvidenceItem,
    MarketSnapshot,
    Money,
    OrderIntent,
    Quantity,
    RiskEvaluation,
    RiskPolicy,
    RiskReasonCode,
    RiskScope,
    content_hash,
)
from kavrigo_domain.base import UtcDatetime
from kavrigo_domain.identifiers import AgentVersionId, WorkspaceId
from kavrigo_domain.money import ExactDecimal
from kavrigo_runtime.contracts import Allocation

Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Name = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")]
Duration = Annotated[int, Field(strict=True, ge=1, le=86_400_000)]
Bps = Annotated[ExactDecimal, Field(ge=0, le=10_000)]


def policy_hash(policy: RiskPolicy) -> str:
    return content_hash(policy.model_dump(mode="python", exclude={"content_hash"}))


class RiskExecutionPolicy(DomainModel):
    """Local USD-spot MARKET/IOC only. Assumptions are operator configuration, not venue facts."""

    execution_policy_id: Annotated[str, Field(pattern=r"^ep_[0-9a-f]{32}$")]
    version: Name
    fee_bps: Bps
    slippage_bps: Bps
    notional_increment_usd: Annotated[ExactDecimal, Field(gt=0)]
    max_snapshot_age_ms: Duration
    max_portfolio_age_ms: Duration
    max_reconciliation_age_ms: Duration
    max_market_age_ms: Duration
    max_approval_age_ms: Duration


class RiskRegistration(DomainModel):
    """All supplied policies apply to this agent; lower scopes cannot relax upper scopes.

    Registration is an authorized service operation, never part of a model/request payload.
    This slice conservatively applies each policy's limits to the entire account portfolio.
    """

    agent_version: AgentVersion
    policies: Annotated[tuple[RiskPolicy, ...], Field(min_length=3, max_length=16)]
    execution: RiskExecutionPolicy
    networks: dict[str, Name]

    @model_validator(mode="after")
    def _bound(self) -> Self:
        version = self.agent_version
        if version.spec_hash != content_hash(version.spec):
            raise ValueError("agent spec hash mismatch")
        if version.spec.execution_policy_ref != self.execution.execution_policy_id:
            raise ValueError("execution policy reference mismatch")
        ids = [p.risk_policy_id for p in self.policies]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate risk policy id")
        scopes = {p.scope for p in self.policies}
        if not {RiskScope.GLOBAL, RiskScope.WORKSPACE, RiskScope.AGENT} <= scopes:
            raise ValueError("global, workspace and agent policies are mandatory")
        if not any(
            p.risk_policy_id == version.spec.risk_policy_ref and p.scope is RiskScope.AGENT
            for p in self.policies
        ):
            raise ValueError("agent risk policy reference mismatch")
        for policy in self.policies:
            expected_workspace = None if policy.scope is RiskScope.GLOBAL else version.workspace_id
            if policy.workspace_id != expected_workspace:
                raise ValueError("risk policy workspace mismatch")
            if policy.content_hash != policy_hash(policy):
                raise ValueError("risk policy hash mismatch")
            if not policy.freshness.required_families:
                raise ValueError("risk requires explicit data families")
            if any(
                f not in policy.freshness.max_age_ms for f in policy.freshness.required_families
            ):
                raise ValueError("required data family has no freshness limit")
        if any(i.value not in self.networks for i in version.spec.universe.instruments):
            raise ValueError("every eligible instrument needs an explicit network group")
        return self


class RiskControls(DomainModel):
    """Trusted supervisor observations. Any active kill stops both buys and sells.

    The local session holds one account, so kills are already filtered to its scope by its
    supervisor. Versions increase on refresh. A model has no method for refreshing controls.
    """

    workspace_id: WorkspaceId
    account_id: Name
    version: Annotated[int, Field(strict=True, ge=1)]
    as_of: UtcDatetime
    valid_until: UtcDatetime
    account_known: bool
    connectivity_ok: bool
    event_calendar_known: bool
    active_kills: tuple[
        Literal["global", "workspace", "account", "agent", "asset", "risk_class"], ...
    ]
    blocked_agent_versions: tuple[AgentVersionId, ...] = ()
    macro_events: Annotated[tuple[UtcDatetime, ...], Field(max_length=128)]
    fencing_token: Annotated[int, Field(strict=True, ge=1)]
    lease_expires_at: UtcDatetime

    @model_validator(mode="after")
    def _window(self) -> Self:
        if min(self.valid_until, self.lease_expires_at) <= self.as_of:
            raise ValueError("control and lease validity windows must be positive")
        return self


class RiskMarket(DomainModel):
    """Frozen normalized market observation provided by the coordinator, never the model."""

    book: BookTicker
    liquidity_usd: Annotated[ExactDecimal, Field(ge=0)]
    observed_at: UtcDatetime


class RiskRequest(DomainModel):
    intent: OrderIntent
    decision: AgentDecision
    allocation: Allocation
    snapshot: MarketSnapshot
    evidence: Annotated[tuple[EvidenceItem, ...], Field(max_length=512)]
    market: RiskMarket


class RiskRecord(DomainModel):
    evaluation: RiskEvaluation
    account_id: Name
    request_hash: Digest
    portfolio_hash: Digest
    registration_hash: Digest
    controls_hash: Digest
    reservations_hash: Digest
    expires_at: UtcDatetime
    max_quantity: Quantity
    max_cash_debit: Money


class PaperRiskPermit(DomainModel):
    """A single local handoff. Step 12 must enforce both quantity and cash ceilings.

    This object is not a signature or an authorization token across a process boundary.
    A future broker must authenticate its issuing risk service and persist idempotency.
    """

    account_id: Name
    approval: ApprovedOrderIntent
    record: RiskRecord


class RiskAuditEvent(DomainModel):
    sequence: Annotated[int, Field(strict=True, ge=1)]
    workspace_id: WorkspaceId
    account_id: Name
    occurred_at: UtcDatetime
    kind: Literal["evaluated", "controls_updated", "handoff"]
    outcome: Annotated[
        str,
        Field(
            pattern=r"^(approved|approved_resized|rejected|updated|expired|recheck_rejected|handed_off)$"
        ),
    ]
    artifact_hash: Digest
    controls_hash: Digest
    reason_codes: tuple[RiskReasonCode, ...] = ()
