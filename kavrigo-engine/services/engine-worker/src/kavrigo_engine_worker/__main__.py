"""Local paper Temporal worker. PostgreSQL owns financial and run artifacts (ADR 0027)."""

import asyncio
import os
import signal
from contextlib import suppress
from datetime import timedelta

import structlog
from pydantic import TypeAdapter
from temporalio.client import Client
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from kavrigo_domain.identifiers import WorkspaceId
from kavrigo_nautilus import NautilusBacktestAdapter
from kavrigo_workflows.accounts import AccountRepository
from kavrigo_workflows.activities import EngineActivities
from kavrigo_workflows.database import EngineDatabase
from kavrigo_workflows.dispatch import dispatch_pending
from kavrigo_workflows.mock_runtime import MockRuntimeBackend
from kavrigo_workflows.runs import RunRepository
from kavrigo_workflows.workflows import WORKFLOWS

_log = structlog.get_logger("kavrigo.engine.worker")


async def _run() -> None:
    if (
        os.getenv("LIVE_TRADING_ENABLED", "false").lower() != "false"
        or os.getenv("DEFAULT_TRADING_MODE", "paper") != "paper"
        or os.getenv("KAVRIGO_ENV", "local") != "local"
    ):
        raise SystemExit("Only local paper operation is enabled (ADR 0027).")
    scopes = TypeAdapter(list[WorkspaceId]).validate_python(
        [
            value.strip()
            for value in os.getenv("KAVRIGO_WORKER_WORKSPACES", "").split(",")
            if value.strip()
        ]
    )
    database = EngineDatabase(os.environ["POSTGRES_DSN"])
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        client = await Client.connect(
            os.getenv("TEMPORAL_ADDRESS", "temporal:7233"),
            namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
            data_converter=pydantic_data_converter,
            interceptors=[TracingInterceptor()],
        )
        queue = os.getenv("TEMPORAL_TASK_QUEUE", "kavrigo-paper-v1")
        runs = RunRepository(database)
        activities = EngineActivities(
            runs,
            AccountRepository(database),
            runtime=MockRuntimeBackend(),
            backtest=NautilusBacktestAdapter(),
        )
        async with Worker(
            client,
            task_queue=queue,
            workflows=WORKFLOWS,
            activities=[activities.resolve, activities.run_stage],
            max_concurrent_activities=4,
            graceful_shutdown_timeout=timedelta(seconds=10),
        ):
            _log.info("worker_started", mode="paper", workflows=4, dispatch_scopes=len(scopes))
            while not stop.is_set():
                for workspace in scopes:
                    try:
                        count = await dispatch_pending(client, runs, workspace, queue)
                        if count:
                            _log.info("runs_dispatched", count=count, workspace_id=workspace)
                    except Exception:
                        _log.warning("run_dispatch_retry", workspace_id=workspace)
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=2)
    finally:
        await database.close()
        _log.info("worker_stopped")


def main() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    asyncio.run(_run())


if __name__ == "__main__":
    main()
