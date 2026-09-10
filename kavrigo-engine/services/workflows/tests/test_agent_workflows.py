import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError

from kavrigo_workflows.accounts import AccountRepository
from kavrigo_workflows.activities import EngineActivities
from kavrigo_workflows.contracts import AccountCommand, RunDefinition, StageRef, StageRequest
from kavrigo_workflows.dispatch import start_run, workflow_id
from kavrigo_workflows.mock_runtime import MockRuntimeBackend
from kavrigo_workflows.runs import RunRepository

from .agent_fixtures import agent_setup as agent_setup
from .conftest import WS, observation
from .test_workflows_integration import replay, worker
from .test_workflows_integration import temporal_client as temporal_client

pytestmark = pytest.mark.integration


class LostActivityAck(EngineActivities):
    failed = False

    @activity.defn(name="kavrigo.run_stage")
    async def run_stage(self, request: StageRequest) -> StageRef:
        result = await super().run_stage(request)
        if request.stage == "execute" and not self.failed:
            self.failed = True
            raise ApplicationError("simulated_ack_loss")
        return result


@pytest.mark.parametrize("backend_kind", ["positive", "default_mock", "unknown", "unconfigured"])
async def test_agent_workflow_recovery(
    engine_database, temporal_client, agent_setup, clock, backend_kind
):
    definition, job, backend, provider = agent_setup
    if backend_kind == "default_mock":
        backend = MockRuntimeBackend()
    if backend_kind == "unconfigured":
        backend = None
    if backend_kind == "unknown":

        class Unknown:
            calls = 0

            async def evaluate(self, job):
                self.calls += 1
                raise ConnectionError("provider acknowledgement unknown")

        backend = Unknown()
    accounts = AccountRepository(engine_database)
    await accounts.create(definition)
    runs = RunRepository(engine_database)
    ref = await runs.create(RunDefinition(workspace_id=WS, run_id="run_" + uuid4().hex, job=job))
    activities = LostActivityAck(runs, accounts, runtime=backend)
    queue = uuid4().hex
    async with worker(temporal_client, activities, queue):
        await start_run(temporal_client, runs, ref, queue)
        handle = temporal_client.get_workflow_handle(workflow_id(ref), result_type=StageRef)
        result = await asyncio.wait_for(handle.result(), 30)
    state = await accounts.read(job.account)
    if backend_kind == "positive":
        assert result.status == "completed"
        assert state.sequence == 1
        assert len(state.state.orders) == 1
        assert provider.call_count == 1
        # Complete the simulated IOC with fresh market data after the retried activity.
        clock.now = datetime.now(UTC)
        lease = await accounts.acquire(job.account, "market-worker")
        filled = await accounts.commit(
            lease, AccountCommand(key="book", generation=1, kind="market", book=observation(clock))
        )
        assert filled.state.orders[0].fills
        await accounts.release(lease)
        # Idempotent execution receipt remains readable under new account ownership.
        lease = await accounts.acquire(job.account, "new-owner")
        try:
            assert await activities._stage(
                StageRequest(run=ref, stage="execute")
            ) == await activities._saved(ref, "execute")
            assert (await accounts.read(job.account)).sequence == 2
        finally:
            await accounts.release(lease)
    else:
        assert not state.state.orders
        assert state.sequence == 0
        if backend_kind == "unknown":
            assert result.status == "uncertain"
            assert backend.calls == 1
        elif backend_kind == "unconfigured":
            assert result.status == "refused"
        else:
            assert result.status == "completed"
            async with engine_database.transaction(WS) as connection:
                saved = await runs.stage(connection, ref, "evaluate")
                output = json.loads(saved["output"])
                assert output["decisions"][0]["proposed_action"] == "no_trade"
    await replay(handle)
