from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import Field

from kavrigo_domain import DecisionProposal, DomainModel, ModelProfile, TradingMode
from kavrigo_model_gateway import (
    AgentAccess,
    CallScope,
    DecisionBudget,
    LocalBudgetLedger,
    LocalModelGateway,
    MockProvider,
    ModelRequest,
    PromptDefinition,
    Route,
    ScopeBudget,
)

WS = "ws_" + "1" * 32
AG = "ag_" + "2" * 32
AV = "av_" + "3" * 32
DEC = "dec_" + "4" * 32


class InputFacts(DomainModel):
    facts: tuple[str, ...] = Field(max_length=8)


class FakeClock:
    def __init__(self):
        self.seconds = 0.0
        self.utc = datetime(2026, 9, 8, 23, 59, 50, tzinfo=UTC)

    def monotonic(self):
        return self.seconds

    def now(self):
        return self.utc + timedelta(seconds=self.seconds)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def request_model():
    return ModelRequest(
        scope=CallScope(
            workspace_id=WS,
            agent_id=AG,
            agent_version_id=AV,
            decision_id=DEC,
            mode=TradingMode.PAPER,
        ),
        idempotency_key="analysis-1",
        profile=ModelProfile.REASON_BALANCED,
        prompt_key="analyze-v1",
        input_json='{"facts":["No reliable evidence available"]}',
    )


@pytest.fixture
def output_json():
    return '{"market_regime":"unknown","state":"unknown","signals":{},"prediction":{"expected_return_bps":0,"confidence":0,"uncertainty":1,"horizon_minutes":60},"proposed_action":"no_trade","reason_codes":["insufficient_evidence"]}'


@pytest.fixture
def route():
    return Route(
        profile=ModelProfile.REASON_BALANCED,
        provider="mock",
        model_identifier="mock-v1",
        pricing_version="fixture-v1",
        input_usd_per_million=Decimal("1"),
        output_usd_per_million=Decimal("2"),
        max_input_tokens=100_000,
        max_output_tokens=4096,
        timeout_ms=1000,
    )


@pytest.fixture
def quota():
    return ScopeBudget(daily_usd=Decimal("100"), calls_per_minute=100, calls_per_day=1000)


@pytest.fixture
def access(quota):
    return AgentAccess(
        workspace_id=WS,
        agent_id=AG,
        agent_version_id=AV,
        profiles=(ModelProfile.REASON_BALANCED,),
        prompt_keys=("analyze-v1",),
        daily_budget=quota,
        decision_budget=DecisionBudget(max_usd=Decimal("1"), max_calls=8, timeout_ms=10_000),
        max_output_tokens=4096,
    )


@pytest.fixture
def prompt():
    return PromptDefinition(
        "analyze-v1",
        ModelProfile.REASON_BALANCED,
        "Assess the supplied facts. Abstain when evidence is weak.",
        InputFacts,
        DecisionProposal,
    )


@pytest.fixture
def build_gateway(clock, route, quota, access, prompt, output_json):
    def build(
        *,
        outputs=None,
        provider=None,
        routes=None,
        agents=None,
        workspaces=None,
        prompts=None,
        capacity=10_000,
        telemetry=None,
    ):
        model = provider or MockProvider(outputs if outputs is not None else [output_json])
        gateway = LocalModelGateway(
            environment="local",
            routes=routes or [route],
            providers=[model],
            prompts=prompts or [prompt],
            agents=agents or [access],
            workspaces=workspaces or {WS: quota},
            ledger=LocalBudgetLedger(environment="local", clock=clock, capacity=capacity),
            telemetry=telemetry,
        )
        return gateway, model

    return build


class BlockedProvider(MockProvider):
    def __init__(self):
        super().__init__([])
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False

    async def complete(self, request):
        self.call_count += 1
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise RuntimeError("deliberately unavailable")


@pytest.fixture
def blocked_provider():
    return BlockedProvider()
