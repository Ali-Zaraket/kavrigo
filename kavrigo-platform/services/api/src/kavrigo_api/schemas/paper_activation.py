"""Paper-activation eligibility assessment contracts."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
type PaperActivationGateName = Literal[
    "policy_approval_integrity",
    "version_policy_binding",
    "evaluation_completion",
    "evaluation_version_binding",
    "promotable_evidence",
    "provider_entitlement",
    "activation_support",
]


class PaperActivationAssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: Annotated[str, Field(pattern=r"^pb_[0-9a-f]{32}$")]
    approval_id: Annotated[str, Field(pattern=r"^pa_[0-9a-f]{32}$")]
    evaluation_run_id: Annotated[str, Field(pattern=r"^run_[0-9a-f]{32}$")]
    agent_spec_hash: Digest
    risk_hash: Digest
    execution_hash: Digest
    evaluation_input_hash: Digest
    reason: Annotated[str, Field(min_length=10, max_length=1000)]


class PaperActivationGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gate: PaperActivationGateName
    passed: bool
    reason_code: Annotated[str, Field(min_length=1, max_length=64)]


class PaperActivationAssessmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: Annotated[str, Field(pattern=r"^paa_[0-9a-f]{32}$")]
    workspace_id: Annotated[str, Field(pattern=r"^ws_[0-9a-f]{32}$")]
    agent_id: Annotated[str, Field(pattern=r"^ag_[0-9a-f]{32}$")]
    agent_version_id: Annotated[str, Field(pattern=r"^av_[0-9a-f]{32}$")]
    version: Annotated[int, Field(strict=True, ge=1)]
    bundle_id: Annotated[str, Field(pattern=r"^pb_[0-9a-f]{32}$")]
    approval_id: Annotated[str, Field(pattern=r"^pa_[0-9a-f]{32}$")]
    evaluation_run_id: Annotated[str, Field(pattern=r"^run_[0-9a-f]{32}$")]
    agent_spec_hash: Digest
    risk_hash: Digest
    execution_hash: Digest
    evaluation_input_hash: Digest
    evaluation_output_hash: Digest | None
    providers: list[str]
    license_refs: list[str]
    gate_results: list[PaperActivationGateResult]
    decision: Literal["blocked", "eligible"]
    reason: str
    assessed_by: str
    assessed_at: datetime
    activation_status: Literal["inactive"] = "inactive"
    execution_enabled: Literal[False] = False
