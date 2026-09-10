import asyncio
import os
import sys
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kavrigo_domain import OrderStatus
from kavrigo_workflows import accounts as accounts_module
from kavrigo_workflows.accounts import AccountRepository
from kavrigo_workflows.contracts import AccountCommand, AccountRef
from kavrigo_workflows.machine import DurableError

from .conftest import change, observation

pytestmark = pytest.mark.integration


@pytest.fixture
async def account(engine_database, definition):
    repository = AccountRepository(engine_database)
    await repository.create(definition)
    ref = AccountRef(
        workspace_id=definition.initial_portfolio.workspace_id, account_id=definition.account_id
    )
    lease = await repository.acquire(ref, "test-worker")
    return repository, ref, lease


async def test_duplicate_concurrency_preserves_one_receipt(account, make_request):
    repository, ref, lease = account
    command = AccountCommand(
        key="same-order", generation=1, kind="orders", requests=(make_request(),)
    )
    receipts = await asyncio.gather(*(repository.commit(lease, command) for _ in range(12)))
    assert all(r == receipts[0] for r in receipts)
    assert receipts[0].sequence == 1
    assert len(receipts[0].state.orders) == 1
    assert (await repository.read(ref)).state == receipts[0].state


async def test_lost_ack_recovers_in_separate_process(account, make_request, clock, monkeypatch):
    repository, ref, lease = account
    await repository.commit(
        lease, AccountCommand(key="order", generation=1, kind="orders", requests=(make_request(),))
    )
    clock.now = datetime.now(UTC)
    command = AccountCommand(
        key="fill", generation=1, kind="market", book=observation(clock, quantity="0.25")
    )

    def lost_ack(*args, **kwargs):
        raise RuntimeError("simulated lost acknowledgement")

    monkeypatch.setattr(repository.log, "info", lost_ack)
    with pytest.raises(RuntimeError, match="lost acknowledgement"):
        await repository.commit(lease, command)
    monkeypatch.undo()
    script = """
import asyncio, os, sys
from kavrigo_workflows.accounts import AccountRepository
from kavrigo_workflows.contracts import AccountRef
from kavrigo_workflows.database import EngineDatabase
async def main():
    db = EngineDatabase(os.environ['RECOVERY_TEST_DSN'])
    try:
        result = await AccountRepository(db).read(AccountRef.model_validate_json(sys.stdin.read()))
        print(result.model_dump_json())
    finally:
        await db.close()
asyncio.run(main())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            **os.environ,
            "RECOVERY_TEST_DSN": repository.db.engine.url.render_as_string(hide_password=False),
        },
    )
    output, errors = await asyncio.wait_for(
        process.communicate(ref.model_dump_json().encode()), timeout=15
    )
    assert process.returncode == 0, errors.decode()
    from kavrigo_workflows.contracts import AccountReceipt

    recovered = AccountReceipt.model_validate_json(output)
    assert recovered.state.orders[0].status is OrderStatus.CANCELLED
    assert len(recovered.state.orders[0].fills) == 1
    retry = await repository.commit(lease, command)
    assert recovered == retry
    assert retry.sequence == 2


async def test_failure_before_commit_rolls_back_issuance_and_outbox(
    account, make_request, monkeypatch
):
    repository, ref, lease = account
    command = AccountCommand(
        key="rollback", generation=1, kind="orders", requests=(make_request(),)
    )

    async def fail_outbox(*args, **kwargs):
        raise RuntimeError("transaction interrupted")

    monkeypatch.setattr(accounts_module, "outbox", fail_outbox)
    with pytest.raises(RuntimeError, match="transaction interrupted"):
        await repository.commit(lease, command)
    assert (await repository.read(ref)).sequence == 0
    monkeypatch.undo()
    result = await repository.commit(lease, command)
    assert len(result.state.orders) == 1
    assert result.sequence == 1


async def test_expired_fence_rejects_new_write_but_allows_receipt_lookup(account):
    repository, ref, lease = account
    command = AccountCommand(key="recorded", generation=1, kind="reconcile")
    result = await repository.commit(lease, command)
    await repository.release(lease)
    replacement = await repository.acquire(ref, "next-worker")
    assert replacement.token > lease.token
    assert await repository.commit(lease, command) == result
    with pytest.raises(DurableError, match="stale_execution_lease"):
        await repository.commit(lease, AccountCommand(key="new", generation=1, kind="reconcile"))


async def test_lease_expiring_during_replay_rolls_back(account, monkeypatch):
    repository, ref, lease = account
    await repository.release(lease)
    lease = await repository.acquire(ref, "short-worker", seconds=1)
    original = repository._machine

    async def delayed(*args):
        result = await original(*args)
        await asyncio.sleep(1.1)
        return result

    monkeypatch.setattr(repository, "_machine", delayed)
    with pytest.raises(DurableError, match="lease_expired_during_command"):
        await repository.commit(
            lease, AccountCommand(key="expired", generation=1, kind="reconcile")
        )
    monkeypatch.undo()
    assert (await repository.read(ref)).sequence == 0


async def test_new_owner_cannot_steal_active_lease(account):
    repository, ref, _ = account
    with pytest.raises(DurableError, match="lease_busy"):
        await repository.acquire(ref, "competing-worker")


async def test_scope_and_immutable_commands(account):
    repository, ref, lease = account
    await repository.commit(lease, AccountCommand(key="audit", generation=1, kind="reconcile"))
    wrong = change(ref, workspace_id="ws_" + "e" * 32)
    with pytest.raises(DurableError, match="account_not_found"):
        await repository.read(wrong)
    async with repository.db.transaction(wrong.workspace_id) as connection:
        assert (
            await connection.execute(text("SELECT count(*) FROM kavrigo.engine_accounts"))
        ).scalar_one() == 0
    with pytest.raises(DBAPIError):
        async with repository.db.transaction(ref.workspace_id) as connection:
            await connection.execute(
                text(
                    "UPDATE kavrigo.engine_commands SET command_key='rewritten' WHERE account_id=:account"
                ),
                {"account": ref.account_id},
            )


async def test_generation_carries_balance_and_old_dedupe(account, make_request, clock):
    repository, ref, lease = account
    order = AccountCommand(key="original", generation=1, kind="orders", requests=(make_request(),))
    original = await repository.commit(lease, order)
    clock.now = datetime.now(UTC)
    filled = await repository.commit(
        lease, AccountCommand(key="book", generation=1, kind="market", book=observation(clock))
    )
    advanced = await repository.commit(
        lease, AccountCommand(key="advance", generation=1, kind="advance")
    )
    assert advanced.generation == 2
    assert advanced.state.cost_basis == filled.state.cost_basis
    assert advanced.state.portfolio.cash == filled.state.portfolio.cash
    assert await repository.commit(lease, order) == original
    assert (await repository.read(ref)).sequence == 3
    with pytest.raises(DurableError, match="generation_conflict"):
        await repository.commit(
            lease, AccountCommand(key="stale-generation", generation=1, kind="reconcile")
        )


async def test_database_rejects_conflicting_key_and_book(account, clock):
    repository, _, lease = account
    command = AccountCommand(key="book", generation=1, kind="market", book=observation(clock))
    original = await repository.commit(lease, command)
    assert await repository.commit(lease, change(command, key="same-book")) == original
    with pytest.raises(DurableError, match="command_idempotency_conflict"):
        await repository.commit(lease, AccountCommand(key="book", generation=1, kind="reconcile"))
    with pytest.raises(DurableError, match="market_idempotency_conflict"):
        await repository.commit(
            lease, change(command, key="different-book", book=observation(clock, quantity="1"))
        )
