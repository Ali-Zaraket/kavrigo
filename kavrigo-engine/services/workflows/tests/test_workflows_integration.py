import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer, Worker

from kavrigo_workflows.accounts import AccountRepository
from kavrigo_workflows.activities import EngineActivities
from kavrigo_workflows.contracts import (
    AccountRef,
    HealthJob,
    HealthObservation,
    RunDefinition,
    StageRef,
    StageRequest,
    SupervisionJob,
)
from kavrigo_workflows.dispatch import dispatch_pending, start_run, workflow_id
from kavrigo_workflows.machine import DurableError
from kavrigo_workflows.runs import RunRepository
from kavrigo_workflows.workflows import WORKFLOWS

from .conftest import WS, change

pytestmark = pytest.mark.integration


def health_definition(**overrides):
    observation = HealthObservation(
        source="fixture", observed_at=datetime.now(UTC), max_age_ms=60000, healthy=True
    )
    return RunDefinition(
        workspace_id=WS,
        run_id="run_" + uuid4().hex,
        job=HealthJob(observations=(change(observation, **overrides),)),
    )


@pytest.fixture
async def temporal_client():
    address = os.getenv("TEST_TEMPORAL_ADDRESS", "localhost:57233")
    host, port = address.rsplit(":", 1)
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), 3)
        writer.close()
        await writer.wait_closed()
    except OSError:
        pytest.skip("Temporal unavailable; run the local stack")
    return await Client.connect(address, data_converter=pydantic_data_converter)


def worker(client, activities, queue):
    return Worker(
        client,
        task_queue=queue,
        workflows=WORKFLOWS,
        activities=[activities.resolve, activities.run_stage],
        graceful_shutdown_timeout=timedelta(seconds=1),
    )


async def replay(handle):
    history = await handle.fetch_history()

    def inspect_payloads(message):
        # JSON history base64-encodes payload bytes. Inspect the actual decoded payloads.
        if message.DESCRIPTOR.full_name == "temporal.api.common.v1.Payload":
            for private in (
                b"initial_portfolio",
                b"rationale",
                b"source_body",
                b"allocated_notional",
            ):
                assert private not in message.data
        for field, value in message.ListFields():
            if field.type == field.TYPE_MESSAGE:
                if field.is_repeated:
                    if field.message_type.GetOptions().map_entry:
                        continue
                    for item in value:
                        inspect_payloads(item)
                else:
                    inspect_payloads(value)

    for event in history.events:
        inspect_payloads(event)
    await Replayer(workflows=WORKFLOWS, data_converter=pydantic_data_converter).replay_workflow(
        history
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "completed"),
        ({"healthy": False}, "refused"),
        ({"sequence_gap": True}, "refused"),
        ({"clock_drift": True}, "refused"),
        ({"divergent": True}, "refused"),
        ({"observed_at": datetime(2020, 1, 1, tzinfo=UTC)}, "refused"),
        ({"observed_at": datetime(2090, 1, 1, tzinfo=UTC)}, "refused"),
    ],
)
async def test_real_health_workflow_and_history(
    engine_database, temporal_client, overrides, expected
):
    runs = RunRepository(engine_database)
    activities = EngineActivities(runs, AccountRepository(engine_database))
    ref = await runs.create(health_definition(**overrides))
    queue = uuid4().hex
    async with worker(temporal_client, activities, queue):
        identity = await start_run(temporal_client, runs, ref, queue)
        handle = temporal_client.get_workflow_handle(identity, result_type=StageRef)
        result = await asyncio.wait_for(handle.result(), 30)
        assert result.status == expected
        assert await start_run(temporal_client, runs, ref, queue) == identity
        assert await runs.finish_run(ref) == result
    await replay(handle)


async def test_supervision_worker_restart_and_lease_change(
    engine_database, temporal_client, definition
):
    accounts = AccountRepository(engine_database)
    await accounts.create(definition)
    account = AccountRef(workspace_id=WS, account_id=definition.account_id)
    runs = RunRepository(engine_database)
    ref = await runs.create(
        RunDefinition(
            workspace_id=WS,
            run_id="run_" + uuid4().hex,
            job=SupervisionJob(account=account, generation=1, cycles=2, interval_seconds=3),
        )
    )
    queue = uuid4().hex
    activities = EngineActivities(runs, accounts)
    async with worker(temporal_client, activities, queue):
        await start_run(temporal_client, runs, ref, queue)
        async with asyncio.timeout(20):
            while (await accounts.read(account)).sequence == 0:  # noqa: ASYNC110 - poll externally committed PostgreSQL state
                await asyncio.sleep(0.05)
    # Re-create repositories and worker while the durable workflow timer is pending.
    accounts = AccountRepository(engine_database)
    replacement = EngineActivities(RunRepository(engine_database), accounts)
    async with worker(temporal_client, replacement, queue):
        handle = temporal_client.get_workflow_handle(workflow_id(ref), result_type=StageRef)
        result = await asyncio.wait_for(handle.result(), 30)
        assert result.status == "completed"
    assert (await accounts.read(account)).sequence == 2
    lease = await accounts.acquire(account, "another-owner")
    try:
        # A completed stage can be read after another worker acquires the account.
        assert (
            await replacement._stage(StageRequest(run=ref, stage="supervise", index=0))
        ).status == "completed"
    finally:
        await accounts.release(lease)
    await replay(handle)


async def test_unknown_dispatch_is_terminal_and_cannot_finish_early(engine_database):
    runs = RunRepository(engine_database)
    ref = await runs.create(health_definition())
    with pytest.raises(DurableError, match="run_has_no_results"):
        await runs.finish_run(ref)
    assert await runs.claim_dispatch(ref, "health", "first") is None
    uncertain = await runs.claim_dispatch(ref, "health", "retry")
    assert uncertain.status == "uncertain"
    async with engine_database.transaction(WS) as connection:
        late = await runs.finish_stage(
            connection, ref, "health", {"late": "output"}, attempt="first"
        )
    assert late == uncertain
    assert (await runs.finish_run(ref)).status == "uncertain"
    with pytest.raises(DurableError, match="run_input_conflict"):
        await runs.create(
            change(
                await runs.load(ref),
                job=HealthJob(
                    observations=(
                        HealthObservation(
                            source="other",
                            observed_at=datetime.now(UTC),
                            max_age_ms=60000,
                            healthy=True,
                        ),
                    )
                ),
            )
        )


async def test_outbox_lost_start_ack_is_idempotent(engine_database, temporal_client, monkeypatch):
    from kavrigo_workflows import dispatch

    runs = RunRepository(engine_database)
    definition = health_definition()
    # Dedicated workspace prevents draining old fixtures into this test's task queue.
    workspace = "ws_" + uuid4().hex
    async with engine_database.transaction(workspace) as connection:
        await connection.execute(
            text(
                "INSERT INTO kavrigo.workspaces(workspace_id,name,slug) VALUES (:ws,'Dispatch',:slug)"
            ),
            {"ws": workspace, "slug": uuid4().hex},
        )
    ref = await runs.create(change(definition, workspace_id=workspace))
    queue = uuid4().hex
    original = dispatch.start_run

    async def lost_ack(*args):
        await original(*args)
        raise ConnectionError("lost start acknowledgement")

    async with worker(
        temporal_client, EngineActivities(runs, AccountRepository(engine_database)), queue
    ):
        monkeypatch.setattr(dispatch, "start_run", lost_ack)
        with pytest.raises(ConnectionError):
            await dispatch_pending(temporal_client, runs, workspace, queue)
        monkeypatch.setattr(dispatch, "start_run", original)
        assert await dispatch_pending(temporal_client, runs, workspace, queue) == 1
        assert await dispatch_pending(temporal_client, runs, workspace, queue) == 0
        handle = temporal_client.get_workflow_handle(workflow_id(ref), result_type=StageRef)
        assert (await asyncio.wait_for(handle.result(), 30)).status == "completed"
    await replay(handle)
