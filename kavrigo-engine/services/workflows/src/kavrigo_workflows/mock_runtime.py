"""Free, explicitly abstaining local model backend. No external provider or credential path."""

from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic

from kavrigo_model_gateway import (
    AgentAccess,
    LocalBudgetLedger,
    LocalModelGateway,
    MockProvider,
    Route,
    ScopeBudget,
)
from kavrigo_runtime import EvaluationResult, LocalAgentRuntime, analysis_prompt
from kavrigo_runtime.analyzer import abstain
from kavrigo_workflows.contracts import AgentJob


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return monotonic()


class MockRuntimeBackend:
    async def evaluate(self, job: AgentJob) -> EvaluationResult:
        version, policy = job.registration.agent_version, job.registration.policy
        prompt = analysis_prompt(version.spec.model_policy.profile)
        quota = ScopeBudget(daily_usd=Decimal(0), calls_per_minute=100, calls_per_day=100)
        clock = Clock()
        gateway = LocalModelGateway(
            environment="local",
            providers=[
                MockProvider(
                    [
                        abstain(
                            job.evaluation.horizon_minutes, "local_mock_no_trade"
                        ).model_dump_json()
                        for _ in range(policy.max_calls_per_cycle)
                    ]
                )
            ],
            prompts=[prompt],
            agents=[
                AgentAccess.from_version(
                    version,
                    daily_budget=quota,
                    prompt_keys=(prompt.key,),
                    max_calls=policy.max_calls_per_cycle,
                )
            ],
            workspaces={version.workspace_id: quota},
            ledger=LocalBudgetLedger(environment="local", clock=clock),
            routes=[
                Route(
                    profile=version.spec.model_policy.profile,
                    provider="mock",
                    model_identifier="mock-v1",
                    pricing_version="local-zero-cost-v1",
                    input_usd_per_million=Decimal(0),
                    output_usd_per_million=Decimal(0),
                    max_input_tokens=100_000,
                    max_output_tokens=4096,
                    timeout_ms=500,
                )
            ],
        )
        runtime = LocalAgentRuntime(
            environment="local", gateway=gateway, registrations=(job.registration,), clock=clock.now
        )
        return await runtime.evaluate(job.evaluation)
