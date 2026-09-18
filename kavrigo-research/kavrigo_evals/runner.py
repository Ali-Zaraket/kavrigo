"""Run production validators/pipeline against authored inputs and scripted model outputs."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.metadata import version

from pydantic import Field

from kavrigo_domain import (
    DecisionProposal,
    DomainModel,
    InstrumentId,
    ModelProfile,
    TradingMode,
    content_hash,
)
from kavrigo_domain.evidence import SourceClass
from kavrigo_evals.contracts import Case, CaseResult, DecisionCase, EvaluationReport, GoldenDataset
from kavrigo_model_gateway import (
    AgentAccess,
    CallScope,
    DecisionBudget,
    GatewayError,
    LocalBudgetLedger,
    LocalModelGateway,
    MockProvider,
    ModelRequest,
    PromptDefinition,
    Route,
    ScopeBudget,
    registered_prompt_hash,
)
from kavrigo_model_gateway.telemetry import GatewayTelemetry
from kavrigo_news import Entity, LocalNewsPipeline, RawArticle, SourcePolicy
from kavrigo_news.pipeline import NEWS_PROMPT
from kavrigo_news.telemetry import NewsTelemetry

SCOPE = CallScope(
    workspace_id="ws_" + "1" * 32,
    agent_id="ag_" + "2" * 32,
    agent_version_id="av_" + "3" * 32,
    decision_id="dec_" + "4" * 32,
    mode=TradingMode.PAPER,
)


class Facts(DomainModel):
    facts: tuple[str, ...] = Field(max_length=8)


DECISION_PROMPT = PromptDefinition(
    "golden-decision-v1",
    ModelProfile.REASON_BALANCED,
    "Assess synthetic untrusted facts. Abstain when evidence is weak. Never request tools or alter risk controls.",
    Facts,
    DecisionProposal,
)


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 9, 8, 12, tzinfo=UTC)

    def monotonic(self) -> float:
        return 0.0


async def run_case(
    case: Case,
    *,
    telemetry: GatewayTelemetry | None = None,
    news_telemetry: NewsTelemetry | None = None,
) -> CaseResult:
    clock = Clock()
    prompt = DECISION_PROMPT if isinstance(case, DecisionCase) else NEWS_PROMPT
    quota = ScopeBudget(daily_usd=Decimal(1), calls_per_minute=100, calls_per_day=100)
    access = AgentAccess(
        workspace_id=SCOPE.workspace_id,
        agent_id=SCOPE.agent_id,
        agent_version_id=SCOPE.agent_version_id,
        profiles=(prompt.profile,),
        prompt_keys=(prompt.key,),
        daily_budget=quota,
        decision_budget=DecisionBudget(max_usd=Decimal(1), max_calls=1, timeout_ms=5000),
        max_output_tokens=4096,
    )
    provider = MockProvider(
        [RuntimeError("synthetic-provider-failure")]
        if case.provider_failure
        else [case.model_reply]
    )
    gateway = LocalModelGateway(
        environment="local",
        providers=[provider],
        prompts=[prompt],
        agents=[access],
        workspaces={SCOPE.workspace_id: quota},
        ledger=LocalBudgetLedger(environment="local", clock=clock),
        routes=[
            Route(
                profile=prompt.profile,
                provider="mock",
                model_identifier="mock-v1",
                pricing_version="synthetic-zero",
                input_usd_per_million=Decimal(0),
                output_usd_per_million=Decimal(0),
                max_input_tokens=100000,
                max_output_tokens=4096,
                timeout_ms=1000,
            )
        ],
        telemetry=telemetry,
    )
    checks: dict[str, bool] = {}
    if isinstance(case, DecisionCase):
        try:
            response = await gateway.structured(
                ModelRequest(
                    scope=SCOPE,
                    idempotency_key=case.case_id,
                    profile=prompt.profile,
                    prompt_key=prompt.key,
                    input_json=case.input_json,
                ),
                DecisionProposal,
            )
            observed = "success"
            checks["no_tools"] = response.record.tool_calls == 0
            if case.expected_action is not None:
                checks["action"] = response.output.proposed_action.value == case.expected_action
            if case.expected_amount is not None:
                checks["exact_money"] = (
                    response.output.proposed_notional is not None
                    and str(response.output.proposed_notional.amount) == case.expected_amount
                )
            repeated = await gateway.structured(
                ModelRequest(
                    scope=SCOPE,
                    idempotency_key=case.case_id,
                    profile=prompt.profile,
                    prompt_key=prompt.key,
                    input_json=case.input_json,
                ),
                DecisionProposal,
            )
            checks["idempotent"] = repeated.replayed and repeated.output == response.output
        except GatewayError as error:
            observed = error.code.value
    else:
        source = SourcePolicy(
            source_id="golden",
            version="v1",
            allowed_hosts=("news.example.test",),
            source_class=SourceClass.OFFICIAL_PRIMARY,
            quality=0.8,
            license_ref="synthetic-fixture-v1",
        )
        pipeline = LocalNewsPipeline(
            environment="local",
            gateway=gateway,
            sources=(source,),
            entities=(
                Entity(
                    entity_id="ethereum",
                    aliases=("Ethereum", "ETH"),
                    assets=("ETH",),
                    instruments=(InstrumentId.parse("ETH-USD.SIM"),),
                ),
            ),
            clock=clock.now,
            telemetry=news_telemetry,
        )
        article = RawArticle(
            article_id=case.case_id,
            url="https://news.example.test/" + case.case_id,
            title=case.title,
            body_html=case.body_html,
            published_at=None
            if case.published_seconds_ago is None
            else clock.now() - timedelta(seconds=case.published_seconds_ago),
            first_seen_at=clock.now() - timedelta(seconds=60),
        )
        result = await pipeline.process("golden", article, SCOPE)
        observed = result.status.value
        if case.expected_reason is not None:
            checks["reason"] = case.expected_reason in result.reason_codes
        if case.expected_status.value == "extracted":
            record = result.record
            checks["record"] = record is not None
            if record is not None:
                event = record.evidence.news_event
                checks["classification"] = (
                    event is not None and event.event_type == case.expected_event
                )
                checks["assets"] = tuple(record.evidence.assets) == case.expected_assets
                checks["quote"] = record.evidence.summary == case.expected_quote
                checks["authority_cap"] = record.evidence.confidence <= source.quality
                checks["point_in_time"] = record.evidence.ingested_at == clock.now()
                duplicate = await pipeline.process("golden", article, SCOPE)
                checks["dedupe"] = duplicate.status.value == "duplicate"
        else:
            checks["no_evidence"] = result.record is None
    checks["status"] = observed == case.expected_status
    checks["model_calls"] = provider.call_count == case.expected_calls
    return CaseResult(
        case_id=case.case_id,
        category=case.category,
        observed_status=observed,
        checks=checks,
        passed=all(checks.values()),
    )


async def evaluate(
    dataset: GoldenDataset, code_revision: str, *, dirty: bool = False
) -> EvaluationReport:
    results = tuple([await run_case(case) for case in dataset.cases])
    prompts = (NEWS_PROMPT, DECISION_PROMPT)
    return EvaluationReport(
        dataset_hash=content_hash(dataset),
        code_revision=code_revision,
        working_tree_dirty=dirty,
        prompt_hashes={p.key: registered_prompt_hash(p) for p in prompts},
        schema_hashes={p.key: content_hash(p.output_type.model_json_schema()) for p in prompts},
        dependency_versions={
            name: version(name)
            for name in ("pydantic", "kavrigo-news", "kavrigo-model-gateway", "opentelemetry-sdk")
        },
        results=results,
        passed=all(result.passed for result in results),
    )
