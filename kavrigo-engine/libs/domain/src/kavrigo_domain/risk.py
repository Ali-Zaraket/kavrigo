"""Deterministic risk policy and evaluation (``MASTER_BUILD_SPEC.md`` §11, ADR 0004).

This module defines the *contract*. The evaluator that consumes it is deterministic code in the
risk service; it is not an agent, and no prompt, tool result or model output can modify a policy
at runtime.

Two properties are load-bearing:

* **The most restrictive applicable rule wins** across the limit hierarchy (§11.2).
* **Fail closed.** Stale data, unknown account state, degraded connectivity or an unapproved
  agent version reject. Absence of information is never treated as permission.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from kavrigo_domain.base import DomainModel, UtcDatetime
from kavrigo_domain.identifiers import DecisionId, OrderIntentId, RiskPolicyId, WorkspaceId
from kavrigo_domain.money import ExactDecimal, Money
from kavrigo_domain.snapshot import DataFamily

__all__ = [
    "EventRiskPolicy",
    "FreshnessPolicy",
    "RiskDecision",
    "RiskEvaluation",
    "RiskLimits",
    "RiskPolicy",
    "RiskReasonCode",
    "RiskScope",
]


class RiskReasonCode(StrEnum):
    """Machine-readable reasons. Rejections must be explainable to the user (§29).

    These are a closed enum rather than free text so that rejection rates can be measured per
    reason, and so a UI can explain "why this trade was rejected" consistently.
    """

    APPROVED = "approved"
    APPROVED_RESIZED = "approved_resized"

    # Data and state integrity — always fail closed.
    STALE_DATA = "stale_data"
    MISSING_DATA_FAMILY = "missing_data_family"
    DATA_QUALITY_BELOW_MINIMUM = "data_quality_below_minimum"
    UNKNOWN_ACCOUNT_STATE = "unknown_account_state"
    RECONCILIATION_STALE = "reconciliation_stale"
    EXCHANGE_CONNECTIVITY_DEGRADED = "exchange_connectivity_degraded"
    CREDENTIAL_STATUS_UNCERTAIN = "credential_status_uncertain"

    # Instrument and venue eligibility.
    UNSUPPORTED_SYMBOL = "unsupported_symbol"
    UNSUPPORTED_INSTRUMENT_CLASS = "unsupported_instrument_class"
    SPREAD_TOO_WIDE = "spread_too_wide"
    INSUFFICIENT_LIQUIDITY = "insufficient_liquidity"

    # Economics.
    EDGE_BELOW_COST_PLUS_MARGIN = "edge_below_cost_plus_margin"
    BELOW_MINIMUM_ORDER_SIZE = "below_minimum_order_size"

    # Exposure limits.
    MAX_POSITION_EXCEEDED = "max_position_exceeded"
    MAX_GROSS_EXPOSURE_EXCEEDED = "max_gross_exposure_exceeded"
    PORTFOLIO_CONCENTRATION_EXCEEDED = "portfolio_concentration_exceeded"
    NETWORK_CONCENTRATION_EXCEEDED = "network_concentration_exceeded"
    MAX_OPEN_POSITIONS_EXCEEDED = "max_open_positions_exceeded"
    INSUFFICIENT_CASH = "insufficient_cash"

    # Circuit breakers.
    DAILY_LOSS_LIMIT_REACHED = "daily_loss_limit_reached"
    DRAWDOWN_CIRCUIT_BREAKER = "drawdown_circuit_breaker"
    KILL_SWITCH_ACTIVE = "kill_switch_active"

    # Governance.
    AGENT_VERSION_NOT_APPROVED = "agent_version_not_approved"
    MODE_NOT_PERMITTED = "mode_not_permitted"
    LIVE_TRADING_DISABLED = "live_trading_disabled"
    SCHEDULED_EVENT_RISK = "scheduled_event_risk"
    EVIDENCE_REQUIREMENTS_NOT_MET = "evidence_requirements_not_met"
    DUPLICATE_INTENT = "duplicate_intent"
    POLICY_VERSION_MISMATCH = "policy_version_mismatch"
    INTENT_EXPIRED = "intent_expired"
    CONTEXT_MISMATCH = "context_mismatch"
    UNSUPPORTED_ORDER_TYPE = "unsupported_order_type"
    EXECUTION_LEASE_EXPIRED = "execution_lease_expired"
    UNSUPPORTED_PRECISION = "unsupported_precision"
    MAX_ORDER_EXCEEDED = "max_order_exceeded"


class RiskScope(StrEnum):
    """The limit hierarchy (``MASTER_BUILD_SPEC.md`` §11.2), most general first."""

    GLOBAL = "global"
    WORKSPACE = "workspace"
    PORTFOLIO = "portfolio"
    NETWORK = "network"
    AGENT = "agent"
    ASSET = "asset"
    ORDER = "order"


Percent = Annotated[ExactDecimal, Field(ge=0, le=100)]


class FreshnessPolicy(DomainModel):
    """Maximum tolerated data age per family, in milliseconds (``MASTER_BUILD_SPEC.md`` §11.3).

    Data freshness is part of risk (``AGENTS.md`` domain rule 5): a correct decision on stale
    data is still a wrong trade.
    """

    max_age_ms: dict[DataFamily, Annotated[int, Field(ge=0)]]
    required_families: Annotated[list[DataFamily], Field(max_length=16)] = []
    min_data_quality: Annotated[float, Field(ge=0.0, le=1.0)] = 0.6

    def limit_for(self, family: DataFamily) -> int | None:
        return self.max_age_ms.get(family)


class EventRiskPolicy(DomainModel):
    """Behaviour around scheduled high-impact events (``MASTER_BUILD_SPEC.md`` §7.13)."""

    block_new_positions_before_macro_minutes: Annotated[int, Field(ge=0, le=1440)] = 10
    block_new_positions_after_macro_minutes: Annotated[int, Field(ge=0, le=1440)] = 5
    reduce_size_pct_during_event_risk: Percent = Decimal(0)


class RiskLimits(DomainModel):
    """Exposure and loss limits. Percentages are of portfolio equity unless stated."""

    max_gross_exposure_pct: Percent
    max_single_asset_exposure_pct: Percent
    max_network_exposure_pct: Percent
    max_open_positions: Annotated[int, Field(ge=0, le=1000)]
    max_daily_loss_pct: Percent
    max_drawdown_pct: Percent
    min_liquidity_usd: ExactDecimal
    max_spread_bps: Annotated[int, Field(ge=0, le=10_000)]
    min_order_notional_usd: ExactDecimal
    max_order_notional_usd: ExactDecimal
    min_edge_over_cost_bps: Annotated[int, Field(ge=0, le=10_000)] = 5
    """Required margin between estimated edge and estimated cost. Trading at zero expected edge
    after costs is a losing strategy with extra steps (§11.1)."""

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.max_single_asset_exposure_pct > self.max_gross_exposure_pct:
            raise ValueError("single-asset exposure limit exceeds the gross exposure limit")
        if self.min_order_notional_usd > self.max_order_notional_usd:
            raise ValueError("min_order_notional_usd exceeds max_order_notional_usd")
        for name in ("min_liquidity_usd", "min_order_notional_usd", "max_order_notional_usd"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        return self


class RiskPolicy(DomainModel):
    """An immutable, versioned risk policy.

    Policies are referenced by id from an ``AgentSpec`` and recorded on every evaluation, so a
    historical rejection can be explained with the policy that actually applied.
    """

    risk_policy_id: RiskPolicyId
    workspace_id: WorkspaceId | None = None
    """``None`` for a platform-level policy that applies to every workspace."""

    version: Annotated[int, Field(ge=1)]
    scope: RiskScope
    limits: RiskLimits
    freshness: FreshnessPolicy
    event_risk: EventRiskPolicy = EventRiskPolicy()
    created_at: UtcDatetime
    created_by: Annotated[str, Field(min_length=1, max_length=128)]
    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class RiskDecision(StrEnum):
    APPROVED = "approved"
    APPROVED_RESIZED = "approved_resized"
    REJECTED = "rejected"


class RiskEvaluation(DomainModel):
    """The deterministic result of evaluating an ``OrderIntent`` against policy.

    Only an ``APPROVED`` or ``APPROVED_RESIZED`` evaluation can produce an
    ``ApprovedOrderIntent``. Nothing else may reach an execution adapter — a property the risk
    service must prove with tests, not assert in a comment.
    """

    risk_evaluation_id: Annotated[str, Field(pattern=r"^re_[0-9a-f]{32}$")]
    order_intent_id: OrderIntentId
    decision_id: DecisionId
    workspace_id: WorkspaceId
    evaluated_at: UtcDatetime
    decision: RiskDecision
    reason_codes: Annotated[list[RiskReasonCode], Field(min_length=1, max_length=32)]
    applied_policy_ids: Annotated[list[RiskPolicyId], Field(min_length=1, max_length=16)]
    binding_scope: RiskScope | None = None
    """Which level of the hierarchy actually bound the outcome — the most restrictive rule."""

    requested_notional: Money
    approved_notional: Money
    evaluator_version: Annotated[str, Field(pattern=r"^v\d+(\.\d+)*$")]
    detail: Annotated[str, Field(max_length=2000)] = ""

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.approved_notional.currency != self.requested_notional.currency:
            raise ValueError("approved and requested notional must share a currency")
        if self.approved_notional.is_negative:
            raise ValueError("approved notional must not be negative")
        if self.approved_notional.amount > self.requested_notional.amount:
            # Risk may only reduce. An engine that can enlarge an order is not a risk control.
            raise ValueError("risk evaluation must never approve more than was requested")

        if self.decision is RiskDecision.REJECTED:
            if not self.approved_notional.is_zero:
                raise ValueError("a rejected evaluation must approve zero notional")
            if RiskReasonCode.APPROVED in self.reason_codes:
                raise ValueError("a rejected evaluation cannot carry the APPROVED reason code")
        else:
            if self.approved_notional.is_zero:
                raise ValueError("an approved evaluation must approve a non-zero notional")
            if self.decision is RiskDecision.APPROVED_RESIZED and (
                self.approved_notional.amount >= self.requested_notional.amount
            ):
                raise ValueError("APPROVED_RESIZED requires a strictly smaller approved notional")
            if self.decision is RiskDecision.APPROVED and (
                self.approved_notional.amount != self.requested_notional.amount
            ):
                raise ValueError("APPROVED requires the full requested notional; use RESIZED")
        return self

    @property
    def is_approved(self) -> bool:
        return self.decision in {RiskDecision.APPROVED, RiskDecision.APPROVED_RESIZED}
