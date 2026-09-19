"""Typed, unapproved paper-policy candidate contracts."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kavrigo_domain import EventRiskPolicy, FreshnessPolicy, RiskLimits, RiskPolicy
from kavrigo_domain.money import ExactDecimal
from kavrigo_risk import RiskExecutionPolicy


class ExecutionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fee_bps: Annotated[ExactDecimal, Field(ge=0, le=10_000)]
    slippage_bps: Annotated[ExactDecimal, Field(ge=0, le=10_000)]
    notional_increment_usd: Annotated[ExactDecimal, Field(gt=0)]
    max_snapshot_age_ms: Annotated[int, Field(strict=True, ge=1, le=86_400_000)]
    max_portfolio_age_ms: Annotated[int, Field(strict=True, ge=1, le=86_400_000)]
    max_reconciliation_age_ms: Annotated[int, Field(strict=True, ge=1, le=86_400_000)]
    max_market_age_ms: Annotated[int, Field(strict=True, ge=1, le=86_400_000)]
    max_approval_age_ms: Annotated[int, Field(strict=True, ge=1, le=86_400_000)]


class PaperPolicyBundleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limits: RiskLimits
    freshness: FreshnessPolicy
    event_risk: EventRiskPolicy = EventRiskPolicy()
    execution: ExecutionCandidate
    reason: Annotated[str, Field(min_length=5, max_length=500)]

    @model_validator(mode="after")
    def _freshness_is_explicit(self) -> Self:
        required = self.freshness.required_families
        if not required or any(f not in self.freshness.max_age_ms for f in required):
            raise ValueError("required data families need explicit age limits")
        return self


class PaperPolicyBundleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: Annotated[str, Field(pattern=r"^pb_[0-9a-f]{32}$")]
    workspace_id: Annotated[str, Field(pattern=r"^ws_[0-9a-f]{32}$")]
    risk: RiskPolicy
    execution: RiskExecutionPolicy
    risk_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    execution_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    approval_status: Literal["unapproved"] = "unapproved"
    execution_enabled: Literal[False] = False
    reason: str
    created_by: str
    created_at: datetime


class PaperPolicyReviewCreate(BaseModel):
    """A second person's recommendation; never an execution authorization."""

    model_config = ConfigDict(extra="forbid")

    recommendation: Literal["advance_to_evaluation", "changes_requested"]
    reason: Annotated[str, Field(min_length=10, max_length=1000)]
    risk_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    execution_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class PaperPolicyReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: Annotated[str, Field(pattern=r"^pr_[0-9a-f]{32}$")]
    bundle_id: Annotated[str, Field(pattern=r"^pb_[0-9a-f]{32}$")]
    workspace_id: Annotated[str, Field(pattern=r"^ws_[0-9a-f]{32}$")]
    recommendation: Literal["advance_to_evaluation", "changes_requested"]
    reason: str
    risk_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    execution_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    reviewed_by: str
    reviewed_at: datetime
    approval_status: Literal["unapproved"] = "unapproved"
    execution_enabled: Literal[False] = False
