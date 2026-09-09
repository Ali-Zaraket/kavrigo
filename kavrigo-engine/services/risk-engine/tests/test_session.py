from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from kavrigo_domain import Position, Price, Quantity, RiskDecision
from kavrigo_risk import RiskGateError

from .conftest import BTC, ETH, WS, change, money, oid, seal


def handoff(session, request, token=1):
    return session.handoff(
        workspace_id=WS, order_intent_id=request.intent.order_intent_id, fencing_token=token
    )


def test_duplicate_commands_and_concurrent_handoffs_are_atomic(build_session, make_request):
    session, request = build_session(), make_request()
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(lambda _: session.evaluate(request), range(24)))
        permits = list(pool.map(lambda _: handoff(session, request), range(24)))
    assert all(record == records[0] for record in records)
    assert sum(permit is not None for permit in permits) == 1


def test_different_requests_cannot_reuse_key_intent_or_decision(build_session, make_request):
    session = build_session()
    original = make_request()
    session.evaluate(original)
    with pytest.raises(RiskGateError, match="idempotency_conflict"):
        session.evaluate(make_request(amount="200"))
    second = make_request(2)
    with pytest.raises(RiskGateError, match="idempotency_conflict"):
        session.evaluate(
            change(
                second,
                intent=change(second.intent, idempotency_key=original.intent.idempotency_key),
            )
        )
    second = change(second, intent=change(second.intent, decision_id=original.intent.decision_id))
    with pytest.raises(RiskGateError, match="decision_already_evaluated"):
        session.evaluate(second)


@pytest.mark.parametrize(
    "failure",
    ["stale", "kill", "lease", "fence", "revoked", "connectivity", "macro", "control_expiry"],
)
def test_handoff_rechecks_fail_closed(failure, build_session, make_request, controls, clock):
    session, request = build_session(), make_request()
    assert session.evaluate(request).evaluation.is_approved
    if failure == "stale":
        clock.now += timedelta(milliseconds=2001)
    elif failure == "lease":
        clock.now = controls.lease_expires_at
    elif failure == "control_expiry":
        clock.now = controls.valid_until
    else:
        updates = {
            "kill": {"active_kills": ("workspace",)},
            "fence": {"fencing_token": 2},
            "revoked": {"blocked_agent_versions": (request.intent.agent_version_id,)},
            "connectivity": {"connectivity_ok": False},
            "macro": {"macro_events": (clock(),)},
        }
        session.update_controls(change(controls, version=2, **updates[failure]))
    assert handoff(session, request) is None
    if failure == "fence":
        assert handoff(session, request, token=2) is None


def test_rejected_intent_never_reaches_paper_consumer(build_session, make_request, controls):
    session = build_session(controls=change(controls, active_kills=("global",)))
    request = make_request()
    assert not session.evaluate(request).evaluation.is_approved
    submitted = []
    permit = handoff(session, request)
    if permit is not None:
        submitted.append(permit)
    assert submitted == []


def test_unknown_submit_result_and_expiry_do_not_release_cash(build_session, make_request, clock):
    session = build_session()
    first = make_request(amount="300")
    approved = session.evaluate(first)
    assert handoff(session, first) is not None
    # The paper consumer crashes after receiving the permit. No acknowledgement can clear risk.
    assert handoff(session, first) is None
    assert session.evaluate(first) == approved
    second = session.evaluate(make_request(2, "300"))
    assert not second.evaluation.is_approved
    clock.now += timedelta(seconds=61)
    assert session.evaluate(first) == approved
    third = session.evaluate(make_request(3, "300"))
    assert not third.evaluation.is_approved  # old portfolio and retained reservations


def test_capacity_never_evicts_prior_approval(build_session, make_request):
    session = build_session(capacity=1)
    first = make_request()
    result = session.evaluate(first)
    with pytest.raises(RiskGateError, match="capacity"):
        session.evaluate(make_request(2))
    assert session.evaluate(first) == result


def test_unfilled_sales_neither_fund_buys_nor_sell_twice(portfolio, build_session, make_request):
    position = Position(
        instrument_id=BTC,
        quantity=Quantity(value="1", asset="BTC"),
        mark_price=Price(value="100", base="BTC", quote="USD"),
        realized_pnl=money(0),
        unrealized_pnl=money(0),
    )
    portfolio = change(
        portfolio,
        cash=money(1),
        equity=money(101),
        gross_exposure=money(100),
        net_exposure=money(100),
        positions=[position],
    )
    session = build_session(portfolio=portfolio)
    sale = session.evaluate(make_request(1, "100", action="close"))
    assert sale.evaluation.is_approved
    assert sale.max_quantity.value <= 1
    repeated = session.evaluate(make_request(2, "100", action="close"))
    assert not repeated.evaluation.is_approved
    buy = session.evaluate(make_request(3, "100", ETH))
    assert not buy.evaluation.is_approved


def test_nested_mutations_cannot_change_registered_policy_or_returned_record(
    registration, build_session, make_request
):
    session = build_session()
    request = make_request()
    first = session.evaluate(request)
    first.evaluation.reason_codes.clear()
    request.evidence[0].injection_signals.append("forged")
    registration.agent_version.approved_environments.clear()
    fresh = make_request()
    assert session.evaluate(fresh).evaluation.reason_codes
    assert handoff(session, fresh) is not None


def test_shared_account_rejects_inconsistent_platform_limits(registration, build_session):
    version = change(registration.agent_version, agent_version_id=oid("av", 9))
    global_policy = registration.policies[0]
    changed_global = seal(
        change(
            global_policy,
            limits=change(global_policy.limits, max_order_notional_usd=Decimal("500")),
        )
    )
    second = change(
        registration, agent_version=version, policies=(changed_global, *registration.policies[1:])
    )
    with pytest.raises(ValueError, match="share upper-scope"):
        build_session(registrations=(registration, second))


def test_missing_upper_policy_and_forged_policy_hash_refuse_registration(registration):
    with pytest.raises(ValueError, match=r"mandatory|at least 3"):
        change(registration, policies=registration.policies[1:])
    policy = change(registration.policies[0], version=2)
    with pytest.raises(ValueError, match="policy hash mismatch"):
        change(registration, policies=(policy, *registration.policies[1:]))


def test_control_refresh_must_advance_and_clock_cannot_move_backwards(
    controls, build_session, make_request, clock
):
    session = build_session()
    request = make_request()
    session.evaluate(request)
    with pytest.raises(RiskGateError, match="control_refresh"):
        session.update_controls(controls)
    clock.now -= timedelta(seconds=1)
    with pytest.raises(RiskGateError, match="clock_moved_backwards"):
        handoff(session, request)


@pytest.mark.parametrize("environment", ["dev", "staging", "paper-prod", "live-prod"])
def test_nondurable_risk_cannot_start_outside_local(environment, build_session):
    with pytest.raises(ValueError, match="local-only"):
        build_session(environment=environment)


@pytest.mark.property
@settings(max_examples=80, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(amounts=st.lists(st.integers(min_value=1, max_value=100_000), min_size=1, max_size=12))
@example(amounts=[29989, 6678])
def test_property_all_concurrent_reservations_stay_within_limits(
    amounts, build_session, make_request
):
    session = build_session()
    records = [
        session.evaluate(make_request(n, str(Decimal(cents) / 100), BTC if n % 2 else ETH))
        for n, cents in enumerate(amounts, 1)
    ]
    approved = [record for record in records if record.evaluation.is_approved]
    total = sum((record.evaluation.approved_notional.amount for record in approved), Decimal(0))
    debit = sum((record.max_cash_debit.amount for record in approved), Decimal(0))
    fees = debit - total
    equity = Decimal(1000) - fees
    assert debit <= 1000
    assert total <= equity * Decimal("0.4")
    for instrument in (BTC, ETH):
        asset_total = sum(
            (
                record.evaluation.approved_notional.amount
                for record in approved
                if record.max_quantity.asset == instrument.base
            ),
            Decimal(0),
        )
        assert asset_total <= equity * Decimal("0.3")
    for record in records:
        assert (
            0
            <= record.evaluation.approved_notional.amount
            <= record.evaluation.requested_notional.amount
        )


@pytest.mark.property
@settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(delay=st.integers(min_value=2001, max_value=100_000))
def test_property_stale_input_never_produces_permit(delay, build_session, make_request, clock):
    start = clock.now
    request = make_request()
    session = build_session()
    clock.now += timedelta(milliseconds=delay)
    try:
        result = session.evaluate(request)
        assert result.evaluation.decision is RiskDecision.REJECTED
        assert handoff(session, request) is None
    finally:
        clock.now = start


@pytest.mark.property
@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(repetitions=st.integers(min_value=2, max_value=25))
def test_property_duplicate_replay_cannot_create_second_submission(
    repetitions, build_session, make_request
):
    session, request = build_session(), make_request()
    record = session.evaluate(request)
    submissions = []
    for _ in range(repetitions):
        assert session.evaluate(request) == record
        permit = handoff(session, request)
        if permit is not None:
            submissions.append(permit.approval.client_order_id)
    assert len(submissions) == 1


def test_existing_risk_can_close_during_loss_breaker(portfolio, build_session, make_request):
    position = Position(
        instrument_id=BTC,
        quantity=Quantity(value="1", asset="BTC"),
        mark_price=Price(value="100", base="BTC", quote="USD"),
        realized_pnl=money(0),
        unrealized_pnl=money(0),
    )
    portfolio = change(
        portfolio,
        cash=money(900),
        gross_exposure=money(100),
        net_exposure=money(100),
        positions=[position],
        realized_pnl_today=money(-50),
    )
    request = make_request(action="close")
    request = change(
        request,
        decision=change(
            request.decision,
            prediction=change(request.decision.prediction, expected_return_bps=100),
        ),
    )
    assert build_session(portfolio=portfolio).evaluate(request).evaluation.is_approved
