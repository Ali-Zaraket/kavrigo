"""Run configuration, results and the reproducibility bundle.

``MASTER_BUILD_SPEC.md`` §12.2 lists what every run must record. The list is long and the
temptation is to record a subset; the bundle below refuses to be constructed without the parts
that make a result re-runnable, because a result nobody can reproduce is an anecdote.

The engine protocol is deliberately narrow. ADR 0012 chose NautilusTrader *behind our own
contracts* precisely so the engine stays replaceable: nothing outside the adapter package
imports a Nautilus symbol.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Protocol, Self, runtime_checkable

from pydantic import Field, model_validator

from kavrigo_backtest.catalog import ParquetBarDatasetRef
from kavrigo_backtest.costs import CostModel
from kavrigo_backtest.fixture import BacktestBar, InlineBarDataset, LongOnlyEmaStrategy
from kavrigo_backtest.governance import ReferenceRiskReplay
from kavrigo_backtest.manifest import DatasetManifest
from kavrigo_backtest.metrics import PerformanceMetrics
from kavrigo_domain import AgentSpec, DomainModel, ModelCallRecord, Money, UtcDatetime, content_hash

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "BacktestRunConfig",
    "ReproducibilityBundle",
    "RunStatus",
]


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUSED = "refused"
    """The run was not attempted because a precondition failed — a leaky dataset, for instance.
    Distinct from ``FAILED`` so that a refusal is never mistaken for a crash, or worse, for a
    result."""


class BacktestRunConfig(DomainModel):
    """Everything needed to start a run, and nothing that could vary between two of them."""

    run_id: Annotated[str, Field(pattern=r"^run_[0-9a-f]{32}$")]
    workspace_id: Annotated[str, Field(pattern=r"^ws_[0-9a-f]{32}$")]
    agent_version_id: Annotated[str, Field(pattern=r"^av_[0-9a-f]{32}$")]
    spec: AgentSpec
    dataset: DatasetManifest
    costs: CostModel
    starting_balance: Money
    benchmark_instrument: Annotated[str | None, Field(default=None, max_length=64)] = None
    inline_data: InlineBarDataset | None = None
    catalog_data: ParquetBarDatasetRef | None = None
    strategy: LongOnlyEmaStrategy | None = None
    risk_replay: ReferenceRiskReplay | None = None
    random_seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 0
    """Pinned even where the engine is deterministic: fill models and any sampling must not
    vary between two runs claiming the same configuration (``MASTER_BUILD_SPEC.md`` §12.2)."""

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.starting_balance.amount <= 0:
            raise ValueError("starting balance must be positive")
        universe = {i.value for i in self.spec.universe.instruments}
        missing = universe - set(self.dataset.instruments)
        if missing:
            raise ValueError(
                f"dataset does not cover every instrument in the agent's universe: "
                f"{sorted(missing)}"
            )
        data_count = int(self.inline_data is not None) + int(self.catalog_data is not None)
        if data_count > 1:
            raise ValueError("a backtest run may select only one historical data source")
        if (data_count == 0) != (self.strategy is None):
            raise ValueError("historical data and its reference strategy must be supplied together")
        if self.strategy is not None:
            if len(self.spec.universe.instruments) != 1:
                raise ValueError("the reference strategy supports exactly one instrument")
            instrument = self.spec.universe.instruments[0]
            if self.strategy.trade_notional.currency != instrument.quote:
                raise ValueError("strategy notional currency must match the instrument quote")
            if self.starting_balance.currency != instrument.quote:
                raise ValueError("starting balance currency must match the instrument quote")
            supported_quote = "USD" if self.risk_replay is not None else "USDT"
            if instrument.quote != supported_quote:
                raise ValueError(
                    f"the current reference path requires {supported_quote} spot for this run"
                )
            if self.benchmark_instrument != instrument.value:
                raise ValueError("reference runs require the configured instrument benchmark")
            if self.catalog_data is not None:
                if self.catalog_data.instrument_id != instrument:
                    raise ValueError("catalog reference must identify the configured instrument")
                if not any(
                    source.content_hash == self.catalog_data.content_hash
                    and source.row_count == self.catalog_data.row_count
                    for source in self.dataset.sources
                ):
                    raise ValueError("catalog dataset is not bound to a matching manifest source")
            if self.inline_data is not None:
                self.validate_bars(self.inline_data.bars)
        if self.risk_replay is not None:
            if self.strategy is None:
                raise ValueError("risk replay requires historical data and a reference strategy")
            replay = self.risk_replay
            version = replay.agent_version
            if (
                version.workspace_id != self.workspace_id
                or version.agent_version_id != self.agent_version_id
                or version.spec != self.spec
            ):
                raise ValueError("risk replay agent version does not match the run")
            if version.created_at > self.dataset.period_start or any(
                policy.created_at > self.dataset.period_start for policy in replay.policies
            ):
                raise ValueError("risk replay versions must exist before the historical period")
            if replay.execution.fee_bps != self.costs.fees.taker_bps:
                raise ValueError("risk replay fee assumptions must match the backtest cost model")
            if replay.execution.slippage_bps != self.costs.slippage.slippage_bps():
                raise ValueError(
                    "risk replay slippage assumptions must match the backtest cost model"
                )
            if (
                self.costs.fees.minimum_fee is not None
                or self.costs.slippage.impact_bps_per_unit_adv != 0
            ):
                raise ValueError(
                    "reference risk replay does not yet model minimum fees or ADV impact"
                )
        return self

    def validate_bars(self, bars: tuple[BacktestBar, ...]) -> None:
        """Validate bytes-loaded bars against the immutable run definition.

        Inline data is checked during model construction. Catalog data is checked after the
        service has resolved and hash-verified the object, before an engine is created.
        """
        if self.strategy is None or (self.inline_data is None and self.catalog_data is None):
            raise ValueError("reference bars require a configured historical data source")
        instrument = self.spec.universe.instruments[0]
        if self.inline_data is not None:
            expected_hash = self.inline_data.content_hash
            expected_rows = len(self.inline_data.bars)
        else:
            assert self.catalog_data is not None
            expected_hash = self.catalog_data.content_hash
            expected_rows = self.catalog_data.row_count
        matching_sources = [
            source for source in self.dataset.sources if source.content_hash == expected_hash
        ]
        if (
            len(bars) != expected_rows
            or not matching_sources
            or all(source.row_count != len(bars) for source in matching_sources)
        ):
            raise ValueError("historical dataset is not bound to a matching manifest source")
        if {bar.instrument_id for bar in bars} != {instrument}:
            raise ValueError("historical bars must cover exactly the configured instrument")
        if len(bars) < self.strategy.slow_period + 2:
            raise ValueError("historical dataset is too short for the configured EMA periods")
        if any(
            bar.event_time < self.dataset.period_start
            or bar.event_time > self.dataset.period_end
            or bar.ingested_at > self.dataset.created_at
            for bar in bars
        ):
            raise ValueError("historical bars fall outside the point-in-time dataset manifest")
        intervals = {bar.interval_seconds for bar in bars}
        if len(intervals) != 1:
            raise ValueError("reference bars must share one interval")
        if self.catalog_data is not None and intervals != {self.catalog_data.interval_seconds}:
            raise ValueError("catalog bar interval does not match its reference")
        price_quantum = Decimal(1).scaleb(-self.strategy.price_precision)
        size_quantum = Decimal(1).scaleb(-self.strategy.size_precision)
        if any(
            value.quantize(price_quantum) != value
            for bar in bars
            for value in (bar.open, bar.high, bar.low, bar.close)
        ) or any(bar.volume.quantize(size_quantum) != bar.volume for bar in bars):
            raise ValueError("historical bars exceed the configured price or size precision")
        if self.strategy.trade_notional.amount < bars[0].close * self.strategy.size_increment:
            raise ValueError("trade notional cannot buy one configured size increment")
        if all(source.last_ingested_at < bars[-1].ingested_at for source in matching_sources):
            raise ValueError("manifest source does not cover the final historical ingestion time")
        if self.risk_replay is not None and len({bar.ingested_at.date() for bar in bars}) != 1:
            raise ValueError("reference risk replay currently supports one UTC day")

    @property
    def config_hash(self) -> str:
        return content_hash(
            {
                "agent_version_id": self.agent_version_id,
                "spec": self.spec,
                "dataset": self.dataset.manifest_hash,
                "costs": self.costs,
                "starting_balance": self.starting_balance,
                "benchmark": self.benchmark_instrument,
                "inline_data": (
                    self.inline_data.content_hash if self.inline_data is not None else None
                ),
                "catalog_data": self.catalog_data,
                "strategy": self.strategy,
                "risk_replay": self.risk_replay,
                "seed": self.random_seed,
            }
        )


class ReproducibilityBundle(DomainModel):
    """The record that makes a result re-runnable (``MASTER_BUILD_SPEC.md`` §12.2).

    Fields are required rather than optional. An optional ``container_image_digest`` becomes an
    absent one, and a run whose code version is unknown cannot be reproduced no matter how
    carefully its data was recorded.
    """

    run_id: Annotated[str, Field(pattern=r"^run_[0-9a-f]{32}$")]
    created_at: UtcDatetime

    dataset_manifest_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    config_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    agent_version_id: Annotated[str, Field(pattern=r"^av_[0-9a-f]{32}$")]
    spec_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    prompt_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    model_profile: Annotated[str, Field(min_length=1, max_length=32)]
    resolved_model_identifier: Annotated[str, Field(min_length=1, max_length=128)]
    """The concrete model, not the profile. A routing fallback must never silently change what
    produced a reproducible result (ADR 0010)."""

    feature_set_version: Annotated[str, Field(pattern=r"^v\d+(\.\d+)*$")]
    feature_manifest_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    risk_policy_id: Annotated[str, Field(pattern=r"^rp_[0-9a-f]{32}$")]
    execution_policy_id: Annotated[str, Field(pattern=r"^ep_[0-9a-f]{32}$")]
    cost_model_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    random_seed: Annotated[int, Field(ge=0)]
    engine_name: Annotated[str, Field(min_length=1, max_length=64)]
    engine_version: Annotated[str, Field(min_length=1, max_length=32)]
    container_image_digest: Annotated[str, Field(min_length=1, max_length=128)]
    code_version: Annotated[str, Field(min_length=1, max_length=64)]
    model_calls: tuple[ModelCallRecord, ...] = ()
    """Actual gateway calls, including failures. Empty for the pre-runtime zero-decision run."""

    def with_model_calls(self, calls: tuple[ModelCallRecord, ...]) -> Self:
        """Bind actual calls instead of inventing provenance for an unexecuted model.

        The legacy singular profile/model/prompt fields describe the primary successful call;
        the complete list retains extraction/analysis attempts with distinct profiles too.
        """
        successful = [call for call in calls if call.outcome == "success"]
        if not successful:
            raise ValueError("a model-backed bundle needs a successful model call")
        if any(
            call.agent_version_id != self.agent_version_id
            or call.request_hash is None
            or call.route_hash is None
            for call in calls
        ):
            raise ValueError("model calls must identify this immutable agent version and request")
        if len({call.workspace_id for call in calls}) != 1 or calls[0].workspace_id is None:
            raise ValueError("model calls must belong to one workspace")
        primary = successful[-1]
        values = self.model_dump()
        values.update(
            model_calls=calls,
            model_profile=primary.profile,
            resolved_model_identifier=primary.resolved_model_identifier,
            prompt_hash=primary.prompt_hash,
        )
        return type(self).model_validate(values)

    @property
    def bundle_hash(self) -> str:
        """One value identifying this exact combination of data, code, policy and model."""
        return content_hash(self)


class BacktestResult(DomainModel):
    """The outcome of a run, with everything a reader needs to judge it.

    ``cost_model`` and ``optimism_warnings`` sit alongside the metrics on purpose. A performance
    number detached from the assumptions that produced it is not a result, and
    ``MASTER_BUILD_SPEC.md`` §33 requires methodology to travel with any shared figure.
    """

    run_id: Annotated[str, Field(pattern=r"^run_[0-9a-f]{32}$")]
    workspace_id: Annotated[str, Field(pattern=r"^ws_[0-9a-f]{32}$")]
    status: RunStatus
    started_at: UtcDatetime
    finished_at: UtcDatetime | None = None
    period_start: UtcDatetime
    period_end: UtcDatetime

    metrics: PerformanceMetrics | None = None
    cost_model: CostModel
    bundle: ReproducibilityBundle
    optimism_warnings: Annotated[list[str], Field(max_length=16)] = []
    leakage_findings: Annotated[list[str], Field(max_length=32)] = []
    refusal_reason: Annotated[str | None, Field(default=None, max_length=1000)] = None
    decisions_evaluated: Annotated[int, Field(ge=0)] = 0
    orders_submitted: Annotated[int, Field(ge=0)] = 0
    orders_rejected_by_risk: Annotated[int, Field(ge=0)] = 0
    risk_evaluations: Annotated[int, Field(ge=0)] = 0
    risk_approvals: Annotated[int, Field(ge=0)] = 0
    risk_replay_hash: Annotated[
        str | None, Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    ] = None
    risk_reason_counts: dict[str, Annotated[int, Field(ge=1)]] = {}
    limitations: Annotated[list[str], Field(max_length=16)] = []

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        if self.status is RunStatus.COMPLETED and self.metrics is None:
            raise ValueError("a completed run must carry metrics")
        if self.status is RunStatus.REFUSED:
            if self.refusal_reason is None:
                raise ValueError("a refused run must say why")
            if self.metrics is not None:
                # A refused run has no result. Attaching metrics would let a leaky dataset
                # produce a number somebody could quote.
                raise ValueError("a refused run must not carry metrics")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at precedes started_at")
        if self.risk_approvals > self.risk_evaluations:
            raise ValueError("risk approvals cannot exceed evaluations")
        if self.orders_rejected_by_risk != self.risk_evaluations - self.risk_approvals:
            raise ValueError("risk rejection count does not match evaluations and approvals")
        if self.risk_evaluations > 0 and self.risk_replay_hash is None:
            raise ValueError("risk-evaluated results must identify the replay configuration")
        if self.risk_evaluations == 0 and self.risk_reason_counts:
            raise ValueError("results without risk evaluations cannot carry risk reason counts")
        return self

    @property
    def is_publishable(self) -> bool:
        """Whether this result may be shown as a performance figure.

        Refused and failed runs are not results; a completed run with leakage findings is a
        result about a dataset that could see the future, which is worse than no figure at all.
        """
        return (
            self.status is RunStatus.COMPLETED
            and not self.leakage_findings
            and not self.limitations
        )


@runtime_checkable
class BacktestEngine(Protocol):
    """What a simulation engine must provide.

    Narrow on purpose. ADR 0012 selected NautilusTrader for its fill realism while keeping our
    contracts independent, so that replacing it is an adapter change rather than a rewrite.
    """

    name: str
    version: str

    def run(
        self, config: BacktestRunConfig, *, bundle: ReproducibilityBundle
    ) -> BacktestResult: ...


def refuse(
    config: BacktestRunConfig,
    *,
    reason: str,
    started_at: UtcDatetime,
    bundle: ReproducibilityBundle,
    findings: list[str],
) -> BacktestResult:
    """Build the result for a run that was not attempted."""
    return BacktestResult(
        run_id=config.run_id,
        workspace_id=config.workspace_id,
        status=RunStatus.REFUSED,
        started_at=started_at,
        finished_at=started_at,
        period_start=config.dataset.period_start,
        period_end=config.dataset.period_end,
        metrics=None,
        cost_model=config.costs,
        bundle=bundle,
        optimism_warnings=config.costs.optimism_warnings,
        leakage_findings=findings,
        refusal_reason=reason,
    )


def cost_model_hash(costs: CostModel) -> str:
    return content_hash(costs)


def default_risk_free_rate() -> Decimal:
    """Zero. A non-zero rate is a modelling assumption that belongs in the run config, not in a
    default nobody notices."""
    return Decimal(0)
