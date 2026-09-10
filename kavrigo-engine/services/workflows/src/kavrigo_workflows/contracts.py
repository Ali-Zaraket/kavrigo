"""Frozen account inputs and small workflow references; no provider or exchange wire types."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from kavrigo_backtest import BacktestRunConfig, ReproducibilityBundle
from kavrigo_domain import DomainModel, PortfolioSnapshot, TradingMode, content_hash
from kavrigo_domain.base import UtcDatetime
from kavrigo_domain.identifiers import WorkspaceId
from kavrigo_paper import PaperAccountState, PaperBook, PaperConfig
from kavrigo_risk import RiskControls, RiskRecord, RiskRegistration, RiskRequest
from kavrigo_risk.contracts import Digest, Name, RiskMarket
from kavrigo_runtime import EvaluationRequest, RuntimeRegistration

Generation = Annotated[int, Field(strict=True, ge=1)]
RunId = Annotated[str, Field(pattern=r"^run_[0-9a-f]{32}$")]


class AccountDefinition(DomainModel):
    account_id: Name
    initial_portfolio: PortfolioSnapshot
    config: PaperConfig
    controls: RiskControls
    registrations: Annotated[tuple[RiskRegistration, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if (
            self.initial_portfolio.mode is not TradingMode.PAPER
            or self.controls.account_id != self.account_id
            or self.controls.workspace_id != self.initial_portfolio.workspace_id
            or any(
                r.agent_version.workspace_id != self.controls.workspace_id
                for r in self.registrations
            )
        ):
            raise ValueError("invalid durable paper scope")
        networks = {item.instrument_id.value: item.network for item in self.config.instruments}
        if any(
            networks.get(instrument) != network
            for registration in self.registrations
            for instrument, network in registration.networks.items()
        ):
            raise ValueError("paper and risk instrument networks must agree")
        return self


class AccountRef(DomainModel):
    workspace_id: WorkspaceId
    account_id: Name


class Lease(AccountRef):
    owner: Name
    token: Generation
    expires_at: UtcDatetime


class AccountCommand(DomainModel):
    key: Name
    generation: Generation
    kind: Literal["orders", "market", "cancel", "controls", "advance", "reconcile"]
    requests: Annotated[tuple[RiskRequest, ...], Field(max_length=32)] = ()
    book: PaperBook | None = None
    client_order_id: Name | None = None
    controls: RiskControls | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        flags = (
            bool(self.requests),
            self.book is not None,
            self.client_order_id is not None,
            self.controls is not None,
        )
        expected = {
            "orders": (True, False, False, False),
            "market": (False, True, False, False),
            "cancel": (False, False, True, False),
            "controls": (False, False, False, True),
            "advance": (False, False, False, False),
            "reconcile": (False, False, False, False),
        }[self.kind]
        if flags != expected:
            raise ValueError("invalid account command shape")
        return self


class AccountReceipt(DomainModel):
    sequence: Annotated[int, Field(strict=True, ge=0)]
    generation: Generation
    state_hash: Digest
    state: PaperAccountState
    risk_records: tuple[RiskRecord, ...] = ()
    committed_at: UtcDatetime


class AccountEvent(DomainModel):
    sequence: Generation
    command: AccountCommand
    occurred_at: UtcDatetime
    state_hash: Digest


class RunRef(DomainModel):
    workspace_id: WorkspaceId
    run_id: RunId
    input_hash: Digest


class StageRef(RunRef):
    stage: Name
    output_hash: Digest
    status: Literal["completed", "refused", "uncertain"]


class AgentJob(DomainModel):
    kind: Literal["agent"] = "agent"
    account: AccountRef
    generation: Generation
    registration: RuntimeRegistration
    evaluation: EvaluationRequest
    markets: dict[str, RiskMarket]


class BacktestJob(DomainModel):
    kind: Literal["backtest"] = "backtest"
    config: BacktestRunConfig
    bundle: ReproducibilityBundle


class HealthObservation(DomainModel):
    source: Name
    observed_at: UtcDatetime
    max_age_ms: Annotated[int, Field(strict=True, ge=1, le=3_600_000)]
    healthy: bool
    sequence_gap: bool = False
    clock_drift: bool = False
    divergent: bool = False


class HealthJob(DomainModel):
    kind: Literal["health"] = "health"
    observations: Annotated[tuple[HealthObservation, ...], Field(min_length=1, max_length=128)]


class SupervisionJob(DomainModel):
    kind: Literal["supervision"] = "supervision"
    account: AccountRef
    generation: Generation
    cycles: Annotated[int, Field(strict=True, ge=1, le=20)] = 1
    interval_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)] = 30


Job = Annotated[AgentJob | BacktestJob | HealthJob | SupervisionJob, Field(discriminator="kind")]


class RunDefinition(DomainModel):
    workspace_id: WorkspaceId
    run_id: RunId
    job: Job

    @model_validator(mode="after")
    def _scope(self) -> Self:
        job = self.job
        if isinstance(job, AgentJob) and (
            job.account.workspace_id != self.workspace_id
            or job.evaluation.workspace_id != self.workspace_id
            or job.registration.agent_version.workspace_id != self.workspace_id
            or job.evaluation.agent_version_id != job.registration.agent_version.agent_version_id
        ):
            raise ValueError("agent job scope mismatch")
        if isinstance(job, BacktestJob) and (
            job.config.workspace_id != self.workspace_id
            or job.config.run_id != self.run_id
            or job.bundle.run_id != self.run_id
            or job.bundle.config_hash != job.config.config_hash
            or job.bundle.agent_version_id != job.config.agent_version_id
            or job.bundle.spec_hash != content_hash(job.config.spec)
        ):
            raise ValueError("backtest job scope mismatch")
        if isinstance(job, SupervisionJob) and job.account.workspace_id != self.workspace_id:
            raise ValueError("supervision scope mismatch")
        return self


class StageRequest(DomainModel):
    run: RunRef
    stage: Literal["resolve", "evaluate", "execute", "backtest", "health", "supervise", "finish"]
    index: Annotated[int, Field(strict=True, ge=0, le=20)] = 0


class RunPlan(DomainModel):
    kind: Literal["agent", "backtest", "health", "supervision"]
    cycles: Annotated[int, Field(strict=True, ge=1, le=20)] = 1
    interval_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)] = 30
