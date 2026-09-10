"""Deterministic outer orchestration. Histories contain references and closed statuses only."""

from datetime import timedelta
from typing import cast

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from kavrigo_workflows.contracts import RunPlan, RunRef, StageRef, StageRequest


RETRIES = RetryPolicy(
    initial_interval=timedelta(seconds=1), maximum_interval=timedelta(seconds=5), maximum_attempts=3
)


async def resolve(ref: RunRef, kind: str) -> RunPlan:
    plan = cast(
        RunPlan,
        await workflow.execute_activity(
            "kavrigo.resolve_run",
            ref,
            result_type=RunPlan,
            start_to_close_timeout=timedelta(seconds=20),
            schedule_to_close_timeout=timedelta(minutes=2),
            retry_policy=RETRIES,
        ),
    )
    if plan.kind != kind:
        raise ApplicationError("workflow_kind_mismatch", non_retryable=True)
    return plan


async def stage(request: StageRequest) -> StageRef:
    return cast(
        StageRef,
        await workflow.execute_activity(
            "kavrigo.run_stage",
            request,
            result_type=StageRef,
            start_to_close_timeout=timedelta(seconds=60),
            schedule_to_close_timeout=timedelta(minutes=4),
            retry_policy=RETRIES,
        ),
    )


@workflow.defn
class AgentEvaluationWorkflow:
    @workflow.run
    async def run(self, ref: RunRef) -> StageRef:
        await resolve(ref, "agent")
        evaluated = await stage(StageRequest(run=ref, stage="evaluate"))
        if evaluated.status == "completed":
            await stage(StageRequest(run=ref, stage="execute"))
        return await stage(StageRequest(run=ref, stage="finish"))


@workflow.defn
class BacktestWorkflow:
    @workflow.run
    async def run(self, ref: RunRef) -> StageRef:
        await resolve(ref, "backtest")
        await stage(StageRequest(run=ref, stage="backtest"))
        return await stage(StageRequest(run=ref, stage="finish"))


@workflow.defn
class DataHealthWorkflow:
    @workflow.run
    async def run(self, ref: RunRef) -> StageRef:
        await resolve(ref, "health")
        await stage(StageRequest(run=ref, stage="health"))
        return await stage(StageRequest(run=ref, stage="finish"))


@workflow.defn
class PaperSupervisionWorkflow:
    @workflow.run
    async def run(self, ref: RunRef) -> StageRef:
        plan = await resolve(ref, "supervision")
        for index in range(plan.cycles):
            result = await stage(StageRequest(run=ref, stage="supervise", index=index))
            if result.status != "completed":
                break
            if index + 1 < plan.cycles:
                await workflow.sleep(timedelta(seconds=plan.interval_seconds))
        return await stage(StageRequest(run=ref, stage="finish"))


WORKFLOWS = [
    AgentEvaluationWorkflow,
    BacktestWorkflow,
    DataHealthWorkflow,
    PaperSupervisionWorkflow,
]
