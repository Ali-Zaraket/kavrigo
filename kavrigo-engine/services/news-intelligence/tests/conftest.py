from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from kavrigo_domain import InstrumentId, ModelProfile, TradingMode
from kavrigo_domain.evidence import NewsEventType, SourceClass
from kavrigo_model_gateway import (
    AgentAccess,
    CallScope,
    DecisionBudget,
    LocalBudgetLedger,
    LocalModelGateway,
    MockProvider,
    Route,
    ScopeBudget,
)
from kavrigo_news import Entity, LocalNewsPipeline, NewsExtraction, RawArticle, SourcePolicy
from kavrigo_news.pipeline import NEWS_PROMPT

WS = "ws_" + "1" * 32
AG = "ag_" + "2" * 32
AV = "av_" + "3" * 32
DEC = "dec_" + "4" * 32
QUOTE = "Ethereum scheduled a protocol upgrade for next week."


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 8, 12, tzinfo=UTC)
        self.seconds = 0.0

    def now(self):
        return self.value + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def scope():
    return CallScope(
        workspace_id=WS, agent_id=AG, agent_version_id=AV, decision_id=DEC, mode=TradingMode.PAPER
    )


@pytest.fixture
def article(clock):
    return RawArticle(
        article_id="fixture-1",
        url="https://news.example.test/story#section",
        title="Scheduled upgrade",
        body_html="<p>" + QUOTE + "</p>",
        published_at=clock.now() - timedelta(minutes=5),
        first_seen_at=clock.now() - timedelta(minutes=1),
    )


@pytest.fixture
def source():
    return SourcePolicy(
        source_id="fixture",
        version="v1",
        allowed_hosts=("news.example.test",),
        source_class=SourceClass.OFFICIAL_PRIMARY,
        quality=0.8,
        license_ref="synthetic-fixture-v1",
    )


@pytest.fixture
def entities():
    return (
        Entity(
            entity_id="ethereum",
            aliases=("Ethereum", "ETH"),
            assets=("ETH",),
            instruments=(InstrumentId.parse("ETH-USD.SIM"),),
        ),
    )


@pytest.fixture
def extraction():
    return NewsExtraction(
        event_type=NewsEventType.PROTOCOL_UPGRADE,
        supporting_quote=QUOTE,
        entity_ids=("ethereum",),
        importance=0.6,
        sentiment=0.1,
        certainty=0.95,
        expected_horizon="weeks",
    )


@pytest.fixture
def build_pipeline(clock, scope, source, entities, extraction):
    def build(*, outputs=None, provider=None, capacity=100, sources=None, telemetry=None):
        quota = ScopeBudget(daily_usd=Decimal("100"), calls_per_minute=1000, calls_per_day=1000)
        access = AgentAccess(
            workspace_id=scope.workspace_id,
            agent_id=scope.agent_id,
            agent_version_id=scope.agent_version_id,
            profiles=(ModelProfile.EXTRACT_FAST,),
            prompt_keys=(NEWS_PROMPT.key,),
            daily_budget=quota,
            decision_budget=DecisionBudget(max_usd=Decimal("2"), max_calls=64, timeout_ms=5000),
            max_output_tokens=4096,
        )
        model = provider or MockProvider(outputs or [extraction.model_dump_json()] * 32)
        gateway = LocalModelGateway(
            environment="local",
            providers=[model],
            prompts=[NEWS_PROMPT],
            agents=[access],
            workspaces={scope.workspace_id: quota},
            routes=[
                Route(
                    profile=ModelProfile.EXTRACT_FAST,
                    provider="mock",
                    model_identifier="mock-v1",
                    pricing_version="fixture-v1",
                    input_usd_per_million=Decimal("0"),
                    output_usd_per_million=Decimal("0"),
                    max_input_tokens=100_000,
                    max_output_tokens=4096,
                    timeout_ms=100,
                )
            ],
            ledger=LocalBudgetLedger(environment="local", clock=clock),
        )
        return LocalNewsPipeline(
            environment="local",
            gateway=gateway,
            sources=sources or (source,),
            entities=entities,
            clock=clock.now,
            capacity=capacity,
            telemetry=telemetry,
        ), model

    return build
