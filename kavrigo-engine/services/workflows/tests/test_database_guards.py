import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kavrigo_workflows.accounts import AccountRepository
from kavrigo_workflows.activities import EngineActivities
from kavrigo_workflows.contracts import AccountRef, StageRequest
from kavrigo_workflows.runs import RunRepository

from .conftest import WS, change
from .test_workflows_integration import health_definition

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE kavrigo.engine_runs SET definition='{}' WHERE run_id=:run",
        "UPDATE kavrigo.engine_runs SET status='queued' WHERE run_id=:run",
        "UPDATE kavrigo.engine_steps SET output='{}' WHERE run_id=:run",
        "DELETE FROM kavrigo.engine_steps WHERE run_id=:run",
        "UPDATE kavrigo.engine_outbox SET payload='{}' WHERE event_id=:run",
        "DELETE FROM kavrigo.engine_runs WHERE run_id=:run",
    ],
)
async def test_database_protects_frozen_inputs_and_terminal_receipts(engine_database, statement):
    runs = RunRepository(engine_database)
    ref = await runs.create(health_definition())
    activities = EngineActivities(runs, AccountRepository(engine_database))
    await activities._stage(StageRequest(run=ref, stage="health"))
    final = await runs.finish_run(ref)
    with pytest.raises(DBAPIError):
        async with engine_database.transaction(WS) as connection:
            await connection.execute(text(statement), {"run": ref.run_id})
    assert await runs.finish_run(ref) == final


async def test_all_engine_tables_enforce_workspace_rls(engine_database, definition):
    accounts = AccountRepository(engine_database)
    await accounts.create(definition)
    runs = RunRepository(engine_database)
    ref = await runs.create(health_definition())
    await EngineActivities(runs, accounts)._stage(StageRequest(run=ref, stage="health"))
    for table in (
        "engine_accounts",
        "engine_commands",
        "engine_runs",
        "engine_steps",
        "engine_outbox",
    ):
        async with engine_database.transaction("ws_" + "9" * 32) as connection:
            assert (
                await connection.execute(
                    text(f"SELECT count(*) FROM kavrigo.{table} WHERE workspace_id=:ws"), {"ws": WS}
                )
            ).scalar_one() == 0
    with pytest.raises(ValueError, match="run_not_found"):
        await runs.load(change(ref, workspace_id="ws_" + "9" * 32))
    with pytest.raises(ValueError, match="account_not_found"):
        await accounts.read(
            AccountRef(workspace_id="ws_" + "9" * 32, account_id=definition.account_id)
        )
