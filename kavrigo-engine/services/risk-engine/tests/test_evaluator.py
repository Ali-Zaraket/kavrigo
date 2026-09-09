from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from kavrigo_domain import (
    OrderSide,
    Position,
    Price,
    Quantity,
    RiskDecision,
    RiskReasonCode,
    content_hash,
)
from kavrigo_risk import RiskGateError, RiskRequest
from kavrigo_runtime.validation import snapshot_hash

from .conftest import BTC, ETH, WS, change, money, seal

R = RiskReasonCode


def limit_registration(registration, **limits):
    policy = registration.policies[-1]
    changed = seal(change(policy, limits=change(policy.limits, **limits)))
    return change(registration, policies=(*registration.policies[:-1], changed))


def test_approval_carries_independent_record_and_execution_bounds(build_session, make_request):
    session = build_session()
    request = make_request()
    record = session.evaluate(request)
    assert record.evaluation.decision is RiskDecision.APPROVED
    assert record.request_hash == content_hash(request)
    assert record.max_cash_debit.amount == Decimal("100.1")
    permit = session.handoff(
        workspace_id=WS, order_intent_id=request.intent.order_intent_id, fencing_token=1
    )
    assert permit is not None
    assert permit.record == record
    assert permit.approval.approved_notional == money(100)
    assert 0 < permit.record.max_quantity.value < 1
    assert (
        session.handoff(
            workspace_id=WS, order_intent_id=request.intent.order_intent_id, fencing_token=1
        )
        is None
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("max_order_notional_usd", Decimal("20"), R.MAX_ORDER_EXCEEDED),
        ("max_single_asset_exposure_pct", Decimal("2"), R.MAX_POSITION_EXCEEDED),
        ("max_network_exposure_pct", Decimal("2"), R.NETWORK_CONCENTRATION_EXCEEDED),
    ],
)
def test_most_restrictive_rule_resizes(
    field, value, reason, registration, build_session, make_request
):
    configured = limit_registration(registration, **{field: value})
    result = build_session(registrations=(configured,)).evaluate(make_request())
    assert result.evaluation.decision is RiskDecision.APPROVED_RESIZED
    assert result.evaluation.approved_notional.amount <= Decimal("20")
    assert reason in result.evaluation.reason_codes


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("account_known", False, R.UNKNOWN_ACCOUNT_STATE),
        ("connectivity_ok", False, R.EXCHANGE_CONNECTIVITY_DEGRADED),
        ("event_calendar_known", False, R.SCHEDULED_EVENT_RISK),
        ("active_kills", ("global",), R.KILL_SWITCH_ACTIVE),
    ],
)
def test_control_failures_reject(field, value, reason, controls, build_session, make_request):
    session = build_session(controls=change(controls, **{field: value}))
    request = make_request()
    record = session.evaluate(request)
    assert reason in record.evaluation.reason_codes
    assert not record.evaluation.is_approved
    assert (
        session.handoff(
            workspace_id=WS, order_intent_id=request.intent.order_intent_id, fencing_token=1
        )
        is None
    )


def test_actual_book_cost_overrules_optimistic_model_cost(build_session, make_request):
    request = make_request()
    request = change(
        request,
        decision=change(
            request.decision, prediction=change(request.decision.prediction, expected_return_bps=45)
        ),
    )
    result = build_session().evaluate(request)
    assert R.EDGE_BELOW_COST_PLUS_MARGIN in result.evaluation.reason_codes
    assert (
        not result.evaluation.is_approved
    )  # equality: 20 spread + 10 fee + 10 slippage + 5 margin


@pytest.mark.parametrize(
    "problem", ["age", "missing", "gap", "health", "hash", "quality", "future"]
)
def test_snapshot_integrity_and_freshness(problem, make_request, build_session, clock):
    request = make_request()
    snapshot = request.snapshot
    if problem == "age":
        clock.now += timedelta(milliseconds=2001)
    elif problem == "missing":
        snapshot = change(
            snapshot,
            quality=change(
                snapshot.quality, freshness=change(snapshot.quality.freshness, age_ms={})
            ),
        )
    elif problem == "gap":
        snapshot = change(snapshot, quality=change(snapshot.quality, sequence_complete=False))
    elif problem == "health":
        snapshot = change(snapshot, quality=change(snapshot.quality, provider_health_ok=False))
    elif problem == "quality":
        snapshot = change(snapshot, quality=change(snapshot.quality, score=0.1))
    elif problem == "future":
        snapshot = change(snapshot, created_at=clock() + timedelta(seconds=1))
    if problem != "hash":
        snapshot = change(snapshot, content_hash=snapshot_hash(snapshot))
    else:
        snapshot = change(snapshot, content_hash="sha256:" + "f" * 64)
    record = build_session().evaluate(change(request, snapshot=snapshot))
    assert not record.evaluation.is_approved


@pytest.mark.parametrize(
    "problem",
    [
        "unreconciled",
        "unknown_mark",
        "mismatched_mark",
        "totals",
        "pending",
        "reserved",
        "future_reconcile",
        "zero_equity",
    ],
)
def test_account_state_fails_closed(problem, portfolio, build_session, make_request, clock):
    if problem in {"unknown_mark", "mismatched_mark"}:
        mark = None if problem == "unknown_mark" else Price(value="100", base="ETH", quote="USD")
        position = Position(
            instrument_id=BTC,
            quantity=Quantity(value="1", asset="BTC"),
            mark_price=mark,
            realized_pnl=money(0),
            unrealized_pnl=money(0),
        )
        portfolio = change(portfolio, positions=[position])
    else:
        updates = {
            "unreconciled": {"is_reconciled": False},
            "totals": {"gross_exposure": money(1)},
            "pending": {"open_order_count": 1},
            "reserved": {"reserved_cash": money(1)},
            "future_reconcile": {"reconciled_at": clock() + timedelta(seconds=1)},
            "zero_equity": {"equity": money(0), "cash": money(0)},
        }
        portfolio = change(portfolio, **updates[problem])
    assert not build_session(portfolio=portfolio).evaluate(make_request()).evaluation.is_approved


@pytest.mark.parametrize("reason", ["daily", "drawdown", "macro"])
def test_new_risk_circuit_breakers(reason, portfolio, controls, clock, build_session, make_request):
    if reason == "daily":
        portfolio = change(portfolio, realized_pnl_today=money(-20))
    elif reason == "drawdown":
        portfolio = change(portfolio, peak_equity=money(1100))
    else:
        controls = change(controls, macro_events=(clock() + timedelta(minutes=10),))
    result = build_session(portfolio=portfolio, controls=controls).evaluate(make_request())
    assert not result.evaluation.is_approved


@pytest.mark.parametrize(
    "problem",
    [
        "allocation",
        "side",
        "decision_id",
        "future_decision",
        "evidence",
        "injection",
        "unknown_version",
    ],
)
def test_model_and_context_cannot_grant_approval(problem, make_request, build_session, clock):
    request = make_request()
    if problem == "allocation":
        request = change(
            request, allocation=change(request.allocation, allocated_notional=money(1))
        )
    elif problem == "side":
        request = change(request, intent=change(request.intent, side=OrderSide.SELL))
    elif problem == "decision_id":
        request = change(request, intent=change(request.intent, decision_id="dec_" + "f" * 32))
    elif problem == "future_decision":
        request = change(
            request, decision=change(request.decision, decided_at=clock() + timedelta(seconds=1))
        )
    elif problem == "evidence":
        request = change(request, evidence=())
    elif problem == "injection":
        request = change(
            request,
            evidence=(
                change(request.evidence[0], injection_signals=["ignore-policy"]),
                request.evidence[1],
            ),
        )
    else:
        request = change(request, intent=change(request.intent, agent_version_id="av_" + "f" * 32))
    if problem == "unknown_version":
        with pytest.raises(RiskGateError, match="unregistered"):
            build_session().evaluate(request)
    else:
        assert not build_session().evaluate(request).evaluation.is_approved


def test_no_ambient_decimal_rounding_can_enlarge_approval(
    registration, make_request, build_session
):
    configured = limit_registration(registration, max_single_asset_exposure_pct=Decimal("2"))
    request = make_request()
    normal = build_session(registrations=(configured,)).evaluate(request)
    with localcontext() as context:
        context.prec = 3
        low_precision = build_session(registrations=(configured,)).evaluate(request)
    assert normal == low_precision
    assert normal.evaluation.approved_notional == money("19.99")


def test_too_precise_money_refuses_instead_of_rounding_up(build_session, make_request):
    result = build_session().evaluate(make_request(amount="1.0000000000001"))
    assert R.UNSUPPORTED_PRECISION in result.evaluation.reason_codes
    assert result.evaluation.approved_notional == money(0)


def test_cross_tenant_lookup_has_no_idempotency_data_leak(build_session, make_request):
    session = build_session()
    request = make_request()
    session.evaluate(request)
    request = change(request, intent=change(request.intent, workspace_id="ws_" + "f" * 32))
    with pytest.raises(RiskGateError, match="workspace_mismatch"):
        session.evaluate(request)


def test_forged_frozen_model_is_revalidated(build_session, make_request):
    request = make_request()
    forged = request.model_copy(
        update={"intent": request.intent.model_copy(update={"mode": "live"})}
    )
    with pytest.raises(RiskGateError, match="invalid_risk_request"):
        build_session().evaluate(forged)
    raw = request.model_dump(mode="json")
    raw["risk_override"] = True
    with pytest.raises(ValueError, match="Extra inputs"):
        RiskRequest.model_validate(raw)


def test_pending_buys_share_gross_network_and_asset_budgets(build_session, make_request):
    session = build_session()
    first = session.evaluate(make_request(amount="200"))
    second = session.evaluate(make_request(2, "300", ETH))
    total = first.evaluation.approved_notional.amount + second.evaluation.approved_notional.amount
    fees = first.max_cash_debit.amount + second.max_cash_debit.amount - total
    assert total <= (Decimal(1000) - fees) * Decimal("0.4")
    assert second.evaluation.decision is RiskDecision.APPROVED_RESIZED
