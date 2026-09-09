from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from kavrigo_domain import RiskDecision, RiskReasonCode, RiskScope
from kavrigo_risk import RiskGateError

from .conftest import ETH, change, money, oid, seal
from .test_evaluator import limit_registration
from .test_session import handoff


def test_binding_scope_is_the_tightest_policy(registration, build_session, make_request):
    configured = limit_registration(registration, max_order_notional_usd=Decimal("20"))
    result = build_session(registrations=(configured,)).evaluate(make_request(amount="1000"))
    assert result.evaluation.approved_notional == money(20)
    assert result.evaluation.binding_scope is RiskScope.AGENT


@pytest.mark.parametrize("zero_depth", [True, False])
def test_top_of_book_depth_caps_approval(zero_depth, make_request, build_session):
    request = make_request()
    size = change(request.market.book.ask_size, value=Decimal(0) if zero_depth else Decimal("0.1"))
    request = change(
        request, market=change(request.market, book=change(request.market.book, ask_size=size))
    )
    result = build_session().evaluate(request)
    assert result.evaluation.approved_notional.amount <= Decimal("10.01")
    assert RiskReasonCode.INSUFFICIENT_LIQUIDITY in result.evaluation.reason_codes
    assert result.evaluation.is_approved is not zero_depth


def test_fee_on_another_asset_cannot_break_prior_concentration(build_session, make_request):
    session = build_session()
    first = session.evaluate(make_request(amount="300"))
    assert first.evaluation.is_approved
    second = session.evaluate(make_request(2, "100", ETH))
    assert not second.evaluation.is_approved
    assert RiskReasonCode.MAX_POSITION_EXCEEDED in second.evaluation.reason_codes


def test_another_agent_cannot_escape_the_accounts_stricter_policy(
    registration, build_session, make_request
):
    tighter = limit_registration(registration, max_single_asset_exposure_pct=Decimal("2"))
    spec = change(registration.agent_version.spec, risk_policy_ref=oid("rp", 44))
    from kavrigo_domain import content_hash

    version = change(
        registration.agent_version,
        agent_version_id=oid("av", 44),
        spec=spec,
        spec_hash=content_hash(spec),
    )
    policy = seal(change(registration.policies[-1], risk_policy_id=oid("rp", 44)))
    looser = change(
        registration, agent_version=version, policies=(*registration.policies[:-1], policy)
    )
    session = build_session(registrations=(tighter, looser))
    request = make_request()
    request = change(
        request,
        intent=change(request.intent, agent_version_id=version.agent_version_id),
        decision=change(request.decision, agent_version_id=version.agent_version_id),
    )
    record = session.evaluate(request)
    assert record.evaluation.approved_notional.amount <= Decimal("20")


def test_expired_lease_is_an_explicit_rejection(controls, clock, make_request, build_session):
    request = make_request()
    clock.now = controls.lease_expires_at
    result = build_session().evaluate(request)
    assert RiskReasonCode.EXECUTION_LEASE_EXPIRED in result.evaluation.reason_codes


def test_mandatory_audit_capacity_fails_closed(controls, build_session, make_request):
    session = build_session(capacity=1)
    request = make_request()
    session.evaluate(request)
    for version in range(2, 5):
        session.update_controls(change(controls, version=version))
    with pytest.raises(RiskGateError, match="audit_capacity"):
        handoff(session, request)
    assert len(session.audit_events) == 4
    assert all(event.outcome != "handed_off" for event in session.audit_events)


@pytest.mark.property
@settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    cause=st.sampled_from(["kill", "state", "data", "evidence", "liquidity", "positions"]),
    amount=st.integers(min_value=1, max_value=10_000),
)
def test_property_rejected_intents_never_produce_execution_handoff(
    cause,
    amount,
    controls,
    registration,
    build_session,
    make_request,
):
    request = make_request(amount=str(amount))
    if cause == "kill":
        controls = change(controls, active_kills=("asset",))
    elif cause == "state":
        controls = change(controls, account_known=False)
    elif cause == "data":
        request = change(
            request,
            market=change(
                request.market, observed_at=request.market.observed_at - timedelta(days=1)
            ),
        )
    elif cause == "evidence":
        request = change(request, evidence=())
    elif cause == "liquidity":
        request = change(request, market=change(request.market, liquidity_usd=Decimal(0)))
    else:
        registration = limit_registration(registration, max_open_positions=0)
    session = build_session(controls=controls, registrations=(registration,))
    record = session.evaluate(request)
    assert record.evaluation.decision is RiskDecision.REJECTED
    assert handoff(session, request) is None
