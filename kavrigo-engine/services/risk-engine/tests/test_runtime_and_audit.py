import json
from decimal import Decimal
from time import monotonic

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from structlog.testing import capture_logs

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
from kavrigo_risk import RiskRequest, RiskTelemetry
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
from .test_session import handoff


@pytest.mark.parametrize("available", [True, False])
async def test_mock_model_runtime_to_risk_handoff(
    available, registration, portfolio, make_request, build_session, clock
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
    if not available:
        assert result.decisions[0].is_abstention
        assert not result.portfolio_decision.allocations
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
    session = build_session(registrations=(registration,))
    assert session.evaluate(request).evaluation.is_approved
    assert handoff(session, request) is not None
    assert handoff(session, request) is None


def test_metadata_telemetry_and_append_only_audit(build_session, make_request, controls):
    traces = TracerProvider()
    exporter = InMemorySpanExporter()
    traces.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    meters = MeterProvider(metric_readers=[reader])
    telemetry = RiskTelemetry(traces.get_tracer("test"), meters.get_meter("test"))
    try:
        session, request = build_session(telemetry=telemetry), make_request()
        with capture_logs() as logs:
            record = session.evaluate(request)
            assert session.evaluate(request) == record
            session.update_controls(change(controls, version=2))
            assert handoff(session, request) is not None
            assert handoff(session, request) is None
        events = session.audit_events
        assert [event.kind for event in events] == ["evaluated", "controls_updated", "handoff"]
        assert [event.sequence for event in events] == [1, 2, 3]
        assert events[0].artifact_hash == content_hash(record)
        assert events[-1].outcome == "handed_off"
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert all(not span.events for span in spans)
        emitted = json.dumps(logs) + json.dumps([dict(span.attributes) for span in spans])
        for private in ("Liquidity improved", "An outage", request.intent.workspace_id, "100.1"):
            assert private not in emitted
        data = reader.get_metrics_data()
        metrics = {
            m.name: m for r in data.resource_metrics for s in r.scope_metrics for m in s.metrics
        }
        assert sum(p.value for p in metrics["kavrigo.risk.evaluations"].data.data_points) == 2
        assert sum(p.value for p in metrics["kavrigo.risk.handoffs"].data.data_points) == 2
    finally:
        traces.shutdown()
        meters.shutdown()
