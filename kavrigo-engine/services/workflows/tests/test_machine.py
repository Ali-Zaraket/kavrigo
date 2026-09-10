from datetime import timedelta

import pytest

from kavrigo_domain import OrderStatus
from kavrigo_workflows.contracts import AccountCommand, AccountEvent
from kavrigo_workflows.machine import AccountMachine, DurableError

from .conftest import BTC, observation


def test_recorded_commands_recover_fills_and_exact_next_generation(definition, make_request, clock):
    machine = AccountMachine(definition)
    commands = [
        AccountCommand(key="orders-1", generation=1, kind="orders", requests=(make_request(),))
    ]
    first = machine.apply(commands[0], clock())
    clock.now += timedelta(milliseconds=100)
    commands.append(
        AccountCommand(
            key="market-1", generation=1, kind="market", book=observation(clock, quantity="0.3333")
        )
    )
    filled = machine.apply(commands[1], clock())
    assert filled.state.orders[0].status is OrderStatus.CANCELLED
    before_basis = filled.state.cost_basis[BTC.value]
    commands.append(AccountCommand(key="advance-1", generation=1, kind="advance"))
    advanced = machine.apply(commands[2], clock())
    assert advanced.generation == 2
    assert advanced.state.cost_basis[BTC.value] == before_basis
    assert advanced.state.portfolio.cash == filled.state.portfolio.cash
    assert advanced.state.fees_paid == filled.state.fees_paid
    assert advanced.state.orders == ()
    events = tuple(
        AccountEvent(
            sequence=r.sequence, command=c, occurred_at=r.committed_at, state_hash=r.state_hash
        )
        for c, r in zip(commands, (first, filled, advanced), strict=True)
    )
    recovered = AccountMachine.reconstruct(definition, events)
    assert recovered.ledger.snapshot() == advanced.state
    assert recovered.chain == advanced.state_hash
    with pytest.raises(DurableError, match="decision_already_processed"):
        recovered.apply(
            AccountCommand(
                key="old-decision", generation=2, kind="orders", requests=(make_request(),)
            ),
            clock(),
        )


def test_cannot_advance_with_open_orders_or_stale_marks(definition, make_request, clock):
    machine = AccountMachine(definition)
    machine.apply(
        AccountCommand(key="order", generation=1, kind="orders", requests=(make_request(),)),
        clock(),
    )
    with pytest.raises(ValueError, match="unsettled_orders"):
        machine.apply(AccountCommand(key="advance", generation=1, kind="advance"), clock())
    clock.now += timedelta(milliseconds=100)
    machine.apply(
        AccountCommand(key="market", generation=1, kind="market", book=observation(clock)), clock()
    )
    clock.now += timedelta(seconds=3)
    with pytest.raises(ValueError, match="fresh_reconciliation"):
        machine.apply(AccountCommand(key="advance", generation=1, kind="advance"), clock())


def test_generation_and_history_hash_fail_closed(definition, clock):
    machine = AccountMachine(definition)
    with pytest.raises(DurableError, match="generation_conflict"):
        machine.apply(AccountCommand(key="wrong", generation=2, kind="reconcile"), clock())
    command = AccountCommand(key="read", generation=1, kind="reconcile")
    event = AccountEvent(
        sequence=1, command=command, occurred_at=clock(), state_hash="sha256:" + "f" * 64
    )
    with pytest.raises(DurableError, match="journal_mismatch"):
        AccountMachine.reconstruct(definition, (event,))


@pytest.mark.parametrize("kind", ["orders", "market", "advance"])
def test_new_day_cannot_reuse_yesterdays_daily_risk_capacity(definition, make_request, clock, kind):
    machine = AccountMachine(definition)
    values = {}
    if kind == "orders":
        values["requests"] = (make_request(),)
    elif kind == "market":
        values["book"] = observation(clock)
    command = AccountCommand(key="next-day", generation=1, kind=kind, **values)
    tomorrow = clock() + timedelta(days=1)
    with pytest.raises(DurableError, match="account_day_rollover_required"):
        machine.apply(command, tomorrow)
    assert machine.sequence == 0
    assert not machine.ledger.orders
    # Reconciliation can age the state but does not reset daily limits or permit new fills.
    machine.apply(AccountCommand(key="reconcile", generation=1, kind="reconcile"), tomorrow)
    with pytest.raises(DurableError, match="account_day_rollover_required"):
        machine.apply(command, tomorrow)
