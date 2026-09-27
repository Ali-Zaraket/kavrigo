"""Inspectable, bounded risk evidence for simulated reference orders (ADR 0042)."""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from kavrigo_domain import (
    DomainModel,
    InstrumentId,
    OrderSide,
    PortfolioSnapshot,
    Quantity,
    RiskDecision,
    TradingMode,
    UtcDatetime,
    content_hash,
)
from kavrigo_domain.identifiers import AgentVersionId, WorkspaceId
from kavrigo_risk.contracts import RiskControls, RiskRecord, RiskRequest

MAX_RISK_RECEIPTS = 5_000
MAX_RISK_AUDIT_BYTES = 8_000_000
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
RiskReplayOutcome = Literal[
    "handed_off", "risk_rejected", "handoff_refused", "below_minimum_order_size", "unavailable"
]


class BacktestRiskReceipt(DomainModel):
    """Diagnostic receipt, never an executable permit or proof of a fill."""

    sequence: Annotated[int, Field(strict=True, ge=1, le=MAX_RISK_RECEIPTS)]
    run_id: Annotated[str, Field(pattern=r"^run_[0-9a-f]{32}$")]
    workspace_id: WorkspaceId
    agent_version_id: AgentVersionId
    risk_replay_hash: Digest
    at: UtcDatetime
    instrument_id: InstrumentId
    side: OrderSide
    outcome: RiskReplayOutcome
    reason_codes: Annotated[
        tuple[Annotated[str, Field(pattern=r"^[a-z_]{1,64}$")], ...],
        Field(min_length=1, max_length=33),
    ]
    request: RiskRequest | None = None
    portfolio: PortfolioSnapshot | None = None
    controls: RiskControls | None = None
    record: RiskRecord | None = None
    handed_off_quantity: Quantity | None = None

    @model_validator(mode="after")
    def _integrity(self) -> Self:
        request, portfolio, controls, record = (
            self.request,
            self.portfolio,
            self.controls,
            self.record,
        )
        if request is not None:
            intent, decision = request.intent, request.decision
            if (
                intent.workspace_id != self.workspace_id
                or decision.workspace_id != self.workspace_id
                or intent.agent_version_id != self.agent_version_id
                or decision.agent_version_id != self.agent_version_id
                or intent.instrument_id != self.instrument_id
                or decision.instrument_id != self.instrument_id
                or intent.side != self.side
                or intent.mode is not TradingMode.BACKTEST
                or intent.created_at != self.at
                or decision.decided_at != self.at
                or request.snapshot.as_of != self.at
                or intent.decision_id != decision.decision_id
                or decision.snapshot_id != request.snapshot.snapshot_id
            ):
                raise ValueError("risk receipt request context mismatch")
        if portfolio is not None and (
            portfolio.workspace_id != self.workspace_id
            or portfolio.mode is not TradingMode.BACKTEST
            or portfolio.as_of != self.at
        ):
            raise ValueError("risk receipt portfolio context mismatch")
        if controls is not None and (
            controls.workspace_id != self.workspace_id or controls.as_of != self.at
        ):
            raise ValueError("risk receipt controls context mismatch")
        if record is not None:
            if request is None or portfolio is None or controls is None:
                raise ValueError("evaluated receipt requires complete frozen inputs")
            evaluation = record.evaluation
            if (
                record.request_hash != content_hash(request)
                or record.portfolio_hash != content_hash(portfolio)
                or record.controls_hash != content_hash(controls)
                or record.account_id != controls.account_id
                or evaluation.order_intent_id != request.intent.order_intent_id
                or evaluation.decision_id != request.decision.decision_id
                or evaluation.workspace_id != self.workspace_id
                or evaluation.evaluated_at != self.at
            ):
                raise ValueError("risk receipt evaluator binding mismatch")
        if self.outcome != "unavailable" and record is None:
            raise ValueError("risk outcome requires an evaluator record")
        if self.outcome == "risk_rejected" and (
            record is None or record.evaluation.decision is not RiskDecision.REJECTED
        ):
            raise ValueError("risk rejection requires a rejected evaluation")
        if self.outcome in ("handed_off", "handoff_refused", "below_minimum_order_size") and (
            record is None or not record.evaluation.is_approved
        ):
            raise ValueError("handoff outcome requires an approved evaluation")
        quantity = self.handed_off_quantity
        if self.outcome == "handed_off":
            if (
                quantity is None
                or quantity.value <= 0
                or quantity.asset != self.instrument_id.base
                or record is None
                or quantity.asset != record.max_quantity.asset
                or quantity.value > record.max_quantity.value
            ):
                raise ValueError("handed-off quantity exceeds or lacks risk approval")
        elif quantity is not None:
            raise ValueError("non-handoff receipt cannot carry an executable quantity")
        expected = (
            tuple(reason.value for reason in record.evaluation.reason_codes) if record else ()
        )
        if self.outcome in ("handoff_refused", "below_minimum_order_size"):
            expected += (self.outcome,)
        elif self.outcome == "unavailable":
            if not self.reason_codes or self.reason_codes[-1] not in (
                "stale_data",
                "unknown_account_state",
            ):
                raise ValueError("unavailable receipt requires a safe failure reason")
            expected += (self.reason_codes[-1],)
        if self.reason_codes != expected:
            raise ValueError("risk receipt reasons do not match its outcome")
        return self


class BacktestRiskAudit(DomainModel):
    schema_version: Literal["reference-risk-audit-v1"] = "reference-risk-audit-v1"
    receipts: Annotated[tuple[BacktestRiskReceipt, ...], Field(max_length=MAX_RISK_RECEIPTS)]
    content_hash: Digest

    @model_validator(mode="after")
    def _integrity(self) -> Self:
        if self.content_hash != content_hash(
            {"schema_version": self.schema_version, "receipts": self.receipts}
        ):
            raise ValueError("risk audit content hash mismatch")
        if [item.sequence for item in self.receipts] != list(range(1, len(self.receipts) + 1)):
            raise ValueError("risk audit receipt sequence is not contiguous")
        times = [item.at for item in self.receipts]
        if times != sorted(times):
            raise ValueError("risk audit receipts are not chronological")
        intent_ids = [
            item.request.intent.order_intent_id
            for item in self.receipts
            if item.request is not None
        ]
        if len(intent_ids) != len(set(intent_ids)):
            raise ValueError("risk audit contains duplicate intents")
        if len(self.model_dump_json().encode("utf-8")) > MAX_RISK_AUDIT_BYTES:
            raise ValueError("risk audit exceeds its byte budget")
        return self

    @property
    def approvals(self) -> int:
        return sum(item.outcome == "handed_off" for item in self.receipts)

    @property
    def reason_counts(self) -> dict[str, int]:
        return dict(Counter(reason for item in self.receipts for reason in item.reason_codes))

    @classmethod
    def seal(cls, receipts: tuple[BacktestRiskReceipt, ...]) -> Self:
        return cls(
            receipts=receipts,
            content_hash=content_hash(
                {"schema_version": "reference-risk-audit-v1", "receipts": receipts}
            ),
        )
