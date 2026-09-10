"""All I/O and domain execution lives in activities, behind durable stage receipts."""

import asyncio
from datetime import timedelta
from typing import Literal, Protocol
from uuid import uuid4

import structlog
from opentelemetry import metrics, trace
from temporalio import activity
from temporalio.exceptions import ApplicationError

from kavrigo_backtest import BacktestEngine, RunStatus
from kavrigo_domain import (
    OrderIntent,
    OrderSide,
    OrderType,
    ProposedAction,
    TradingMode,
    content_hash,
)
from kavrigo_risk import RiskRequest
from kavrigo_risk.evaluator import age_ms
from kavrigo_runtime import EvaluationResult, EvaluationStatus
from kavrigo_workflows.accounts import AccountRepository, outbox
from kavrigo_workflows.contracts import (
    AccountCommand,
    AgentJob,
    BacktestJob,
    HealthJob,
    RunPlan,
    RunRef,
    StageRef,
    StageRequest,
    SupervisionJob,
)
from kavrigo_workflows.database import db_now, encode
from kavrigo_workflows.machine import DurableError
from kavrigo_workflows.runs import RunRepository


class RuntimeBackend(Protocol):
    async def evaluate(self, job: AgentJob) -> EvaluationResult: ...


class EngineActivities:
    def __init__(
        self,
        runs: RunRepository,
        accounts: AccountRepository,
        *,
        runtime: RuntimeBackend | None = None,
        backtest: BacktestEngine | None = None,
    ) -> None:
        self.runs, self.accounts = runs, accounts
        self.runtime, self.backtest = runtime, backtest
        self.tracer = trace.get_tracer("kavrigo.workflows")
        self.counter = metrics.get_meter("kavrigo.workflows").create_counter(
            "kavrigo.workflow.stages"
        )
        self.log = structlog.get_logger(__name__)

    @activity.defn(name="kavrigo.resolve_run")
    async def resolve(self, ref: RunRef) -> RunPlan:
        try:
            definition = await self.runs.load(ref)
            job = definition.job
            return RunPlan(
                kind=job.kind,
                cycles=job.cycles if isinstance(job, SupervisionJob) else 1,
                interval_seconds=job.interval_seconds if isinstance(job, SupervisionJob) else 30,
            )
        except ValueError:
            raise ApplicationError("invalid_run_reference", non_retryable=True) from None
        except Exception:
            raise ApplicationError("run_reference_unavailable", type="StageUnavailable") from None

    @activity.defn(name="kavrigo.run_stage")
    async def run_stage(self, request: StageRequest) -> StageRef:
        try:
            with self.tracer.start_as_current_span(
                "workflow.stage", record_exception=False, set_status_on_exception=False
            ):
                result = await self._stage(request)
            self.counter.add(1, {"stage": request.stage, "status": result.status})
            self.log.info("workflow_stage", stage=request.stage, status=result.status)
            return result
        except DurableError as error:
            if str(error) == "account_lease_busy":
                raise ApplicationError("account_lease_busy", type="AccountBusy") from None
            raise ApplicationError(
                "stage_refused", type="StageRefused", non_retryable=True
            ) from None
        except ValueError:
            raise ApplicationError("invalid_stage_artifact", non_retryable=True) from None
        except Exception:
            # Database errors can contain SQL parameters; never serialize them into Temporal.
            raise ApplicationError(
                "stage_temporarily_unavailable", type="StageUnavailable"
            ) from None

    async def _stage(self, request: StageRequest) -> StageRef:
        ref = request.run
        definition = await self.runs.load(ref)
        job = definition.job
        if request.stage == "finish":
            return await self.runs.finish_run(ref)
        if request.stage == "evaluate" and isinstance(job, AgentJob):
            return await self._evaluate(ref, job)
        if request.stage == "execute" and isinstance(job, AgentJob):
            return await self._execute(ref, job)
        if request.stage == "supervise" and isinstance(job, SupervisionJob):
            if request.index >= job.cycles:
                raise DurableError("supervision_index_invalid")
            name = f"supervise.{request.index}"
            saved = await self._saved(ref, name)
            if saved is not None:
                return saved
            lease = await self.accounts.acquire(job.account, ref.run_id)
            try:
                async with self.runs.db.transaction(ref.workspace_id) as connection:
                    await self.runs.load_in_transaction(connection, ref, lock=True)
                    previous = await self.runs.stage(connection, ref, name)
                    if previous:
                        return self.runs.stage_ref(ref, previous)
                    receipt, _ = await self.accounts.commit_in_transaction(
                        connection,
                        lease,
                        AccountCommand(
                            key=f"{ref.run_id}.{name}", generation=job.generation, kind="reconcile"
                        ),
                    )
                    status: Literal["completed", "refused"] = (
                        "completed" if receipt.state.portfolio.is_reconciled else "refused"
                    )
                    return await self.runs.finish_stage(
                        connection, ref, name, receipt, status=status
                    )
            finally:
                await self.accounts.release(lease)
        async with self.runs.db.transaction(ref.workspace_id) as connection:
            await self.runs.load_in_transaction(connection, ref, lock=True)
            previous = await self.runs.stage(connection, ref, request.stage)
            if previous:
                return self.runs.stage_ref(ref, previous)
            if request.stage == "health" and isinstance(job, HealthJob):
                now = await db_now(connection)
                failed = tuple(
                    o.source
                    for o in job.observations
                    if (
                        not o.healthy
                        or o.sequence_gap
                        or o.clock_drift
                        or o.divergent
                        or not 0 <= age_ms(now, o.observed_at) <= o.max_age_ms
                    )
                )
                result = await self.runs.finish_stage(
                    connection,
                    ref,
                    "health",
                    {"checked_at": now.isoformat(), "unhealthy_sources": list(failed)},
                    status="refused" if failed else "completed",
                )
                if failed:
                    await outbox(
                        connection,
                        ref.workspace_id,
                        "data.unhealthy",
                        "health-" + ref.run_id,
                        encode(result),
                    )
                return result
            if request.stage == "backtest" and isinstance(job, BacktestJob):
                if self.backtest is None:
                    return await self.runs.finish_stage(
                        connection,
                        ref,
                        "backtest",
                        {"reason": "backend_unconfigured"},
                        status="refused",
                    )
                backtest_result = await asyncio.to_thread(
                    self.backtest.run, job.config, bundle=job.bundle
                )
                if (
                    backtest_result.workspace_id != ref.workspace_id
                    or backtest_result.run_id != ref.run_id
                    or backtest_result.bundle != job.bundle
                ):
                    raise DurableError("backtest_result_mismatch")
                # Preserve the actual artifact, but never call a zero-decision adapter run a
                # successful research workflow. The strategy/data carry-over remains explicit.
                status = (
                    "completed"
                    if backtest_result.status is RunStatus.COMPLETED
                    and backtest_result.decisions_evaluated > 0
                    else "refused"
                )
                return await self.runs.finish_stage(
                    connection, ref, "backtest", backtest_result, status=status
                )
        raise DurableError("stage_kind_mismatch")

    async def _evaluate(self, ref: RunRef, job: AgentJob) -> StageRef:
        attempt = uuid4().hex
        previous = await self.runs.claim_dispatch(ref, "evaluate", attempt)
        if previous is not None:
            return previous
        if self.runtime is None:
            async with self.runs.db.transaction(ref.workspace_id) as connection:
                await self.runs.load_in_transaction(connection, ref, lock=True)
                return await self.runs.finish_stage(
                    connection,
                    ref,
                    "evaluate",
                    {"reason": "runtime_unconfigured"},
                    status="refused",
                    attempt=attempt,
                )
        result = await self.runtime.evaluate(job)
        if (
            result.workspace_id != ref.workspace_id
            or result.agent_version_id != job.evaluation.agent_version_id
            or result.request_hash != content_hash(job.evaluation)
            or result.runtime_policy_hash != content_hash(job.registration.policy)
        ):
            raise DurableError("runtime_result_mismatch")
        async with self.runs.db.transaction(ref.workspace_id) as connection:
            await self.runs.load_in_transaction(connection, ref, lock=True)
            return await self.runs.finish_stage(
                connection,
                ref,
                "evaluate",
                result,
                status="completed" if result.status is EvaluationStatus.COMPLETED else "refused",
                attempt=attempt,
            )

    async def _saved(self, ref: RunRef, name: str) -> StageRef | None:
        async with self.runs.db.transaction(ref.workspace_id) as connection:
            await self.runs.load_in_transaction(connection, ref)
            previous = await self.runs.stage(connection, ref, name)
            return self.runs.stage_ref(ref, previous) if previous is not None else None

    async def _execute(self, ref: RunRef, job: AgentJob) -> StageRef:
        saved = await self._saved(ref, "execute")
        if saved is not None:
            return saved
        lease = await self.accounts.acquire(job.account, ref.run_id)
        try:
            async with self.runs.db.transaction(ref.workspace_id) as connection:
                await self.runs.load_in_transaction(connection, ref, lock=True)
                previous = await self.runs.stage(connection, ref, "execute")
                if previous:
                    return self.runs.stage_ref(ref, previous)
                evaluated = await self.runs.stage(connection, ref, "evaluate")
                if evaluated is None or self.runs.stage_ref(ref, evaluated).status != "completed":
                    raise DurableError("evaluation_not_complete")
                result = EvaluationResult.model_validate_json(evaluated["output"])
                allocation = result.portfolio_decision
                if allocation is None or not allocation.allocations:
                    return await self.runs.finish_stage(
                        connection, ref, "execute", {"orders": 0, "reason": "abstained"}
                    )
                now = await db_now(connection)
                decisions = {d.decision_id: d for d in result.decisions}
                requests = []
                for proposed in allocation.allocations:
                    decision = decisions[proposed.decision_id]
                    if decision.is_abstention or proposed.allocated_notional.amount <= 0:
                        continue
                    key = content_hash({"run": ref.run_id, "decision": decision.decision_id})[7:39]
                    intent = OrderIntent(
                        order_intent_id="oi_" + key,
                        decision_id=decision.decision_id,
                        workspace_id=ref.workspace_id,
                        agent_version_id=decision.agent_version_id,
                        instrument_id=decision.instrument_id,
                        mode=TradingMode.PAPER,
                        side=OrderSide.BUY
                        if decision.proposed_action is ProposedAction.BUY
                        else OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        notional=proposed.allocated_notional,
                        idempotency_key="workflow-" + key,
                        created_at=now,
                        expires_at=now + timedelta(seconds=30),
                    )
                    requests.append(
                        RiskRequest(
                            intent=intent,
                            decision=decision,
                            allocation=proposed,
                            snapshot=job.evaluation.snapshot,
                            evidence=job.evaluation.evidence,
                            market=job.markets[decision.instrument_id.value],
                        )
                    )
                if not requests:
                    return await self.runs.finish_stage(
                        connection, ref, "execute", {"orders": 0, "reason": "abstained"}
                    )
                # Guard the frozen account generation as well as its number. Agent allocation
                # cannot be transplanted onto a different portfolio with the same generation.
                account = await self.accounts._account(connection, lease, lock=True)
                machine = await self.accounts._machine(connection, lease, account)
                if content_hash(
                    machine.ledger.initial
                ) != allocation.portfolio_hash or allocation.portfolio_hash != content_hash(
                    job.evaluation.portfolio
                ):
                    raise DurableError("runtime_portfolio_mismatch")
                receipt, _ = await self.accounts.commit_in_transaction(
                    connection,
                    lease,
                    AccountCommand(
                        key=ref.run_id + ".orders",
                        generation=job.generation,
                        kind="orders",
                        requests=tuple(requests),
                    ),
                )
                return await self.runs.finish_stage(connection, ref, "execute", receipt)
        finally:
            await self.accounts.release(lease)
