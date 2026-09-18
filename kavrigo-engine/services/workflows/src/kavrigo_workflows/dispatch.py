"""Workspace-scoped PostgreSQL outbox to Temporal; duplicate starts reuse durable receipts."""

from contextlib import suppress
from datetime import timedelta

from sqlalchemy import text
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from kavrigo_domain import content_hash
from kavrigo_workflows.contracts import RunRef, StageRef
from kavrigo_workflows.runs import RunRepository

WORKFLOW_NAMES = {
    "agent": "AgentEvaluationWorkflow",
    "backtest": "BacktestWorkflow",
    "health": "DataHealthWorkflow",
    "supervision": "PaperSupervisionWorkflow",
}


def workflow_id(ref: RunRef) -> str:
    return "kavrigo-" + content_hash({"workspace": ref.workspace_id, "run": ref.run_id})[7:]


async def start_run(client: Client, runs: RunRepository, ref: RunRef, queue: str) -> str:
    definition = await runs.load(ref)
    identity = workflow_id(ref)
    # PostgreSQL's immutable inputs and receipts remain authoritative after retention.
    with suppress(WorkflowAlreadyStartedError):
        await client.start_workflow(
            WORKFLOW_NAMES[definition.job.kind],
            ref,
            id=identity,
            task_queue=queue,
            result_type=StageRef,
            execution_timeout=timedelta(hours=24),
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            rpc_timeout=timedelta(seconds=10),
        )
    return identity


async def dispatch_run(client: Client, runs: RunRepository, ref: RunRef, queue: str) -> str:
    """Start one authorized frozen run, then acknowledge its durable outbox event."""
    identity = await start_run(client, runs, ref, queue)
    async with runs.db.transaction(ref.workspace_id) as connection:
        await connection.execute(
            text("""UPDATE kavrigo.engine_outbox SET delivered_at=clock_timestamp()
            WHERE workspace_id=:ws AND event_id=:event AND topic='run.queued'
            AND delivered_at IS NULL"""),
            {"ws": ref.workspace_id, "event": ref.run_id},
        )
    return identity


async def dispatch_pending(client: Client, runs: RunRepository, workspace: str, queue: str) -> int:
    async with runs.db.transaction(workspace) as connection:
        pending = (
            (
                await connection.execute(
                    text("""SELECT event_id,payload FROM kavrigo.engine_outbox
            WHERE workspace_id=:ws AND topic='run.queued' AND delivered_at IS NULL
            ORDER BY created_at,event_id LIMIT 100"""),
                    {"ws": workspace},
                )
            )
            .mappings()
            .all()
        )
    delivered = 0
    for event in pending:
        ref = RunRef.model_validate_json(event["payload"])
        if ref.workspace_id != workspace:
            raise ValueError("outbox_scope_mismatch")
        # A crash before this acknowledgement leaves the event pending; starting
        # the same workflow ID again is safe.
        await dispatch_run(client, runs, ref, queue)
        delivered += 1
    return delivered
