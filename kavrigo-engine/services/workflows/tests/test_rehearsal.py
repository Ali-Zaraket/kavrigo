"""Synthetic rehearsal inputs must remain scoped, immutable and unable to trade."""

import asyncio
import json
from uuid import uuid4

import pytest

from kavrigo_model_gateway import registered_prompt_hash
from kavrigo_runtime import analysis_prompt
from kavrigo_workflows.accounts import AccountRepository
from kavrigo_workflows.activities import EngineActivities
from kavrigo_workflows.contracts import AccountRef, StageRef
from kavrigo_workflows.dispatch import start_run, workflow_id
from kavrigo_workflows.machine import DurableError
from kavrigo_workflows.mock_runtime import MockRuntimeBackend
from kavrigo_workflows.rehearsal import build_rehearsal, persist_rehearsal, rehearsal_run_id
from kavrigo_workflows.runs import RunRepository

from .conftest import BTC, WS
from .test_workflows_integration import temporal_client as temporal_client
from .test_workflows_integration import worker


def test_rehearsal_is_scoped_and_fail_closed(registration, clock):
    version = registration.agent_version
    account, run = build_rehearsal(version, key="first-launch", at=clock())
    assert run.run_id == rehearsal_run_id(WS, "first-launch")
    assert run.workspace_id == WS
    assert run.job.account.account_id == account.account_id
    assert account.controls.active_kills == ("global",)
    assert account.controls.connectivity_ok is False
    assert all(
        policy.limits.max_gross_exposure_pct == 0 for policy in account.registrations[0].policies
    )
    assert run.job.evaluation.snapshot.quality.notes == [
        "synthetic_rehearsal_only",
        "not_live_market_data",
    ]
    assert len({e.evidence_id for e in run.job.evaluation.evidence}) == 4
    assert all(e.provider == "kavrigo-synthetic" for e in run.job.evaluation.evidence)
    assert all(i.value in run.job.markets for i in (BTC,))


def test_rehearsal_run_id_is_keyed_to_workspace():
    assert rehearsal_run_id(WS, "retry") == rehearsal_run_id(WS, "retry")
    assert rehearsal_run_id(WS, "retry") != rehearsal_run_id("ws_" + "2" * 32, "retry")


def test_browser_uuid_key_is_normalized_for_runtime_contract(registration, clock):
    key = str(uuid4())
    _, run = build_rehearsal(registration.agent_version, key=key, at=clock())
    assert run.job.evaluation.idempotency_key == "rehearsal-" + run.run_id[4:]


@pytest.mark.integration
async def test_rehearsal_persists_once_and_reuses_frozen_input(
    engine_database, registration, clock
):
    version = registration.agent_version
    key = "replay-" + uuid4().hex
    first, replayed = await persist_rehearsal(engine_database, version, key=key, at=clock())
    assert not replayed
    again, replayed = await persist_rehearsal(engine_database, version, key=key, at=clock())
    assert replayed
    assert again == first
    altered = version.model_copy(update={"agent_version_id": "av_" + "f" * 32})
    with pytest.raises(DurableError, match="idempotency_conflict"):
        await persist_rehearsal(engine_database, altered, key=key, at=clock())


@pytest.mark.integration
async def test_rehearsal_real_temporal_run_abstains_and_creates_no_order(
    engine_database, temporal_client, registration, clock
):
    original = registration.agent_version
    version = original.model_copy(
        update={
            "prompt_hash": registered_prompt_hash(
                analysis_prompt(original.spec.model_policy.profile)
            )
        }
    )
    ref, _ = await persist_rehearsal(
        engine_database, version, key="workflow-" + uuid4().hex, at=clock()
    )
    accounts = AccountRepository(engine_database)
    runs = RunRepository(engine_database)
    activities = EngineActivities(runs, accounts, runtime=MockRuntimeBackend())
    queue = uuid4().hex
    async with worker(temporal_client, activities, queue):
        await start_run(temporal_client, runs, ref, queue)
        receipt = await asyncio.wait_for(
            temporal_client.get_workflow_handle(workflow_id(ref), result_type=StageRef).result(),
            30,
        )
    assert receipt.status == "completed"
    account = await accounts.read(
        AccountRef(workspace_id=WS, account_id="rehearsal-" + ref.run_id[4:])
    )
    assert account.sequence == 0
    assert account.state.orders == ()
    async with engine_database.transaction(WS) as connection:
        saved = await runs.stage(connection, ref, "evaluate")
        output = json.loads(saved["output"])
        assert all(d["proposed_action"] == "no_trade" for d in output["decisions"])
