from datetime import timedelta
from decimal import Decimal
from time import monotonic

import pytest

from kavrigo_domain import DecisionProposal, FeatureVector, content_hash
from kavrigo_model_gateway import (
    AgentAccess,
    LocalBudgetLedger,
    LocalModelGateway,
    MockProvider,
    Route,
    ScopeBudget,
    registered_prompt_hash,
)
from kavrigo_paper import LocalPaperBroker, LocalPaperVenue, replay
from kavrigo_risk import RiskRequest
from kavrigo_runtime import (
    EvaluationRequest,
    LocalAgentRuntime,
    RuntimePolicy,
    RuntimeRegistration,
    ScannerPolicy,
    analysis_prompt,
    snapshot_hash,
)

from .conftest import BTC, HASH, WS, change
from .test_paper import book
from .test_paper import config as config


@pytest.mark.parametrize("available", [True, False])
async def test_mock_model_runtime_to_paper_replay(
    available, registration, portfolio, make_request, build_session, clock, config
):
    template = make_request()
    spec = change(
        registration.agent_version.spec,
        analysis=change(registration.agent_version.spec.analysis, network_context=False),
    )
    prompt = analysis_prompt(spec.model_policy.profile)
    version = change(
        registration.agent_version,
        spec=spec,
        spec_hash=content_hash(spec),
        prompt_hash=registered_prompt_hash(prompt),
    )
    registration = change(registration, agent_version=version)
    quota = ScopeBudget(daily_usd=Decimal("100"), calls_per_minute=100, calls_per_day=100)
    access = AgentAccess.from_version(
        version, daily_budget=quota, prompt_keys=(prompt.key,), max_calls=1
    )
    proposal = DecisionProposal.model_validate(
        template.decision.model_dump(
            mode="python",
            exclude={
                "decision_id",
                "workspace_id",
                "agent_version_id",
                "snapshot_id",
                "instrument_id",
                "decided_at",
                "model_calls",
            },
        )
    )
    provider = MockProvider(
        [proposal.model_dump_json() if available else RuntimeError("provider unavailable")]
    )

    class GatewayClock:
        def now(self):
            return clock()

        def monotonic(self):
            return monotonic()

    gateway = LocalModelGateway(
        environment="local",
        providers=[provider],
        prompts=[prompt],
        agents=[access],
        workspaces={WS: quota},
        ledger=LocalBudgetLedger(environment="local", clock=GatewayClock()),
        routes=[
            Route(
                profile=spec.model_policy.profile,
                provider="mock",
                model_identifier="mock-v1",
                pricing_version="fixture",
                input_usd_per_million=Decimal(0),
                output_usd_per_million=Decimal(0),
                max_input_tokens=100_000,
                max_output_tokens=4096,
                timeout_ms=500,
            )
        ],
    )
    values = {"return_5m": Decimal("0.02")}
    feature = FeatureVector(
        instrument_id=BTC,
        feature_set_version="v1",
        values=values,
        content_hash=content_hash(
            {"instrument_id": BTC.value, "feature_set_version": "v1", "values": values}
        ),
    )
    snapshot = change(template.snapshot, features=[feature])
    snapshot = change(snapshot, content_hash=snapshot_hash(snapshot))
    policy = RuntimePolicy(
        version="fixture",
        code_version="fixture",
        code_image_digest=HASH,
        scanner=ScannerPolicy(
            absolute_thresholds={"return_5m": Decimal("0.001")},
            candidate_ttl_ms=5000,
            max_candidates=2,
        ),
        max_snapshot_age_ms=5000,
        max_portfolio_age_ms=5000,
        max_calls_per_cycle=1,
        allocation_groups=registration.networks,
        max_new_allocation_pct=Decimal(50),
        max_group_exposure_pct=Decimal(40),
        fee_buffer_bps=Decimal(10),
    )
    runtime = LocalAgentRuntime(
        environment="local",
        gateway=gateway,
        registrations=(RuntimeRegistration(agent_version=version, policy=policy),),
        clock=clock,
    )
    result = await runtime.evaluate(
        EvaluationRequest(
            workspace_id=WS,
            agent_version_id=version.agent_version_id,
            idempotency_key="runtime-risk-integration",
            horizon_minutes=60,
            snapshot=snapshot,
            portfolio=portfolio,
            evidence=template.evidence,
        )
    )
    assert provider.call_count == 1
    assert len(result.decisions) == 1
    assert result.portfolio_decision is not None
    session = build_session(registrations=(registration,))
    venue = LocalPaperVenue(
        environment="local",
        account_id="paper-account-one",
        initial_portfolio=portfolio,
        config=config,
        risk=session,
        clock=clock,
    )
    broker = LocalPaperBroker(workspace_id=WS, venue=venue)
    if not available:
        assert result.decisions[0].is_abstention
        assert not result.portfolio_decision.allocations
        assert broker.state.orders == ()
        assert venue.export_replay(workspace_id=WS).entries == ()
        return
    decision = result.decisions[0]
    allocation = result.portfolio_decision.allocations[0]
    intent = change(
        template.intent, decision_id=decision.decision_id, notional=allocation.allocated_notional
    )
    request = RiskRequest(
        intent=intent,
        decision=decision,
        allocation=allocation,
        snapshot=snapshot,
        evidence=template.evidence,
        market=template.market,
    )
    assert session.evaluate(request).evaluation.is_approved
    order = broker.submit(order_intent_id=intent.order_intent_id, fencing_token=1)
    assert order is not None
    clock.now += timedelta(milliseconds=100)
    broker.observe(book(clock))
    assert broker.state.orders[0].fills
    assert broker.state.portfolio.positions
    assert broker.state.portfolio.cash.amount < portfolio.cash.amount
    assert replay(venue.export_replay(workspace_id=WS)) == broker.state
    assert (
        session.handoff(workspace_id=WS, order_intent_id=intent.order_intent_id, fencing_token=1)
        is None
    )
