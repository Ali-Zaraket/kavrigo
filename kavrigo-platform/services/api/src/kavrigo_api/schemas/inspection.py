"""Read-only product projections. Engine commands remain behind the engine boundary."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from kavrigo_backtest import BacktestRiskReceipt, CostModel
from kavrigo_domain import AgentDecision, EvidenceItem, Money, PortfolioSnapshot


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    kind: Literal["agent", "backtest", "health", "supervision"]
    input_kind: Literal["recorded", "synthetic_rehearsal", "testnet_rehearsal"] = "recorded"
    status: Literal["queued", "running", "completed", "refused", "uncertain"]
    input_hash: str
    created_at: datetime


class StageSummary(BaseModel):
    stage: str
    status: Literal["started", "completed", "refused", "uncertain"]
    output_hash: str | None
    started_at: datetime
    finished_at: datetime | None


class RunInspection(RunSummary):
    stages: list[StageSummary]
    decisions: list[AgentDecision]
    evidence: list[EvidenceItem]
    reason_codes: list[str]


class BacktestRiskPage(BaseModel):
    """A bounded view of a stored diagnostic risk journal, never an order permit."""

    model_config = ConfigDict(extra="forbid")
    run_id: str
    run_status: Literal["queued", "running", "completed", "refused", "uncertain"]
    journal_state: Literal["pending", "unavailable", "recorded"]
    audit_hash: str | None
    risk_replay_hash: str | None
    bundle_hash: str | None
    dataset_manifest_hash: str | None
    cost_model: CostModel | None
    risk_evaluations: int
    risk_approvals: int
    risk_reason_counts: dict[str, int]
    limitations: list[str]
    items: list[BacktestRiskReceipt]
    has_more: bool
    next_cursor: str | None


class PaperAccountView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str
    sequence: int
    state_hash: str
    committed_at: datetime
    portfolio: PortfolioSnapshot
    fees_paid: Money


class AuditSummary(BaseModel):
    event_id: str
    action: str
    resource_type: str
    resource_id: str
    occurred_at: datetime
