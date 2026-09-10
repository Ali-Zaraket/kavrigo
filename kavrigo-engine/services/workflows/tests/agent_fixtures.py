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
from kavrigo_runtime import (
    EvaluationRequest,
    LocalAgentRuntime,
    RuntimePolicy,
    RuntimeRegistration,
    ScannerPolicy,
    analysis_prompt,
    snapshot_hash,
)
from kavrigo_workflows.contracts import AccountRef, AgentJob

from .conftest import BTC, HASH, WS, change


@pytest.fixture
def agent_setup(registration, portfolio, make_request, clock, definition):
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
    provider = MockProvider([proposal.model_dump_json()])

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
    evaluation = EvaluationRequest(
        workspace_id=WS,
        agent_version_id=version.agent_version_id,
        idempotency_key="durable-runtime-fixture",
        horizon_minutes=60,
        snapshot=snapshot,
        portfolio=portfolio,
        evidence=template.evidence,
    )
    definition = change(definition, registrations=(registration,))
    job = AgentJob(
        account=AccountRef(workspace_id=WS, account_id=definition.account_id),
        generation=1,
        registration=RuntimeRegistration(agent_version=version, policy=policy),
        evaluation=evaluation,
        markets={BTC.value: template.market},
    )

    class Backend:
        async def evaluate(self, job):
            return await runtime.evaluate(job.evaluation)

    return definition, job, Backend(), provider
