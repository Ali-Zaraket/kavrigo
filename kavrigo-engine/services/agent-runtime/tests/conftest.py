from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from kavrigo_domain import (
    AgentSpec,
    AgentVersion,
    AnalysisConfig,
    DataPack,
    DataQuality,
    DecisionProposal,
    EvidenceItem,
    EvidenceRequirements,
    FeatureVector,
    FreshnessReport,
    InstrumentId,
    MarketSnapshot,
    ModelPolicy,
    ModelProfile,
    Money,
    PortfolioSnapshot,
    ScheduleConfig,
    TradingMode,
    UniverseConfig,
    content_hash,
)
from kavrigo_domain.evidence import EvidenceKind, SourceClass
from kavrigo_domain.snapshot import DataFamily
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
    FrozenNetworkContexts,
    LocalAgentRuntime,
    NetworkContext,
    RuntimePolicy,
    RuntimeRegistration,
    ScannerPolicy,
    analysis_prompt,
    network_hash,
    snapshot_hash,
)

WS = "ws_" + "1" * 32
AV = "av_" + "2" * 32
AG = "ag_" + "3" * 32
BTC = InstrumentId.parse("BTC-USD.SIM")
ETH = InstrumentId.parse("ETH-USD.SIM")
HASH = "sha256:" + "1" * 64


class Clock:
    def __init__(self):
        self.utc = datetime(2026, 9, 8, 12, tzinfo=UTC)
        self.seconds = 0.0

    def now(self):
        return self.utc + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def version(clock):
    spec = AgentSpec(
        name="fixture-agent",
        universe=UniverseConfig(instruments=[BTC, ETH]),
        schedule=ScheduleConfig(decision_interval_seconds=60, max_decisions_per_day=10),
        data_packs=[DataPack.NEWS, DataPack.PRICE_TECHNICAL],
        analysis=AnalysisConfig(),
        model_policy=ModelPolicy(max_cost_per_decision_usd=Decimal("1"), timeout_seconds=1),
        evidence=EvidenceRequirements(min_evidence_items=2),
        risk_policy_ref="rp_" + "4" * 32,
        execution_policy_ref="ep_" + "5" * 32,
    )
    return AgentVersion(
        agent_id=AG,
        agent_version_id=AV,
        workspace_id=WS,
        version=1,
        spec=spec,
        spec_hash=content_hash(spec),
        prompt_version_id="pv_" + "6" * 32,
        prompt_hash=registered_prompt_hash(analysis_prompt()),
        feature_set_version="v1",
        created_at=clock.now() - timedelta(days=1),
        created_by="fixture",
    )


def seal_feature(instrument, values):
    return FeatureVector(
        instrument_id=instrument,
        feature_set_version="v1",
        values=values,
        content_hash=content_hash(
            {"instrument_id": instrument.value, "feature_set_version": "v1", "values": values}
        ),
    )


def seal_snapshot(snapshot):
    return snapshot.model_copy(update={"content_hash": snapshot_hash(snapshot)})


@pytest.fixture
def evidence(clock):
    return tuple(
        EvidenceItem(
            evidence_id="ev_" + str(n) * 32,
            kind=EvidenceKind.NEWS,
            source_class=SourceClass.SPECIALIST_PUBLICATION,
            provider="fixture",
            summary=summary,
            observed_at=clock.now() - timedelta(minutes=5),
            ingested_at=clock.now() - timedelta(minutes=1),
            content_hash=content_hash(summary),
            quality=0.8,
            confidence=0.7,
            is_contradictory_candidate=n == 2,
            license_ref="synthetic-v1",
        )
        for n, summary in [
            (1, "Liquidity improved in the synthetic market."),
            (2, "Synthetic market outage remains possible."),
        ]
    )


@pytest.fixture
def portfolio(clock):
    def money(value):
        return Money(amount=Decimal(value), currency="USD")

    return PortfolioSnapshot(
        workspace_id=WS,
        mode=TradingMode.PAPER,
        as_of=clock.now(),
        base_currency="USD",
        cash=money("1000"),
        reserved_cash=money("0"),
        realized_pnl_today=money("0"),
        unrealized_pnl=money("0"),
        equity=money("1000"),
        gross_exposure=money("0"),
        net_exposure=money("0"),
        peak_equity=money("1000"),
        reconciled_at=clock.now(),
    )


@pytest.fixture
def request_cycle(clock, portfolio, evidence):
    snapshot = MarketSnapshot(
        snapshot_id="snap_" + "7" * 32,
        as_of=clock.now(),
        created_at=clock.now(),
        instruments=[BTC, ETH],
        features=[
            seal_feature(BTC, {"return_5m": Decimal("0.02")}),
            seal_feature(ETH, {"return_5m": Decimal("0.01")}),
        ],
        evidence_refs=[e.evidence_id for e in evidence],
        quality=DataQuality(score=0.9, freshness=FreshnessReport(age_ms={DataFamily.TRADES: 0})),
        content_hash=HASH,
    )
    return EvaluationRequest(
        workspace_id=WS,
        agent_version_id=AV,
        idempotency_key="cycle-one",
        horizon_minutes=60,
        snapshot=seal_snapshot(snapshot),
        portfolio=portfolio,
        evidence=evidence,
    )


@pytest.fixture
def contexts(clock, evidence):
    value = NetworkContext(
        context_id="market-context-v1",
        scope="network.crypto",
        instruments=(BTC, ETH),
        known_at=clock.now() - timedelta(seconds=1),
        valid_until=clock.now() + timedelta(minutes=10),
        health="normal",
        liquidity_flow_score=0.5,
        activity_score=0.5,
        risk_score=0.2,
        evidence_refs=tuple(item.evidence_id for item in evidence),
        content_hash=HASH,
    )
    return (value.model_copy(update={"content_hash": network_hash(value)}),)


@pytest.fixture
def policy():
    return RuntimePolicy(
        version="fixture-v1",
        code_version="fixture",
        code_image_digest=HASH,
        scanner=ScannerPolicy(
            absolute_thresholds={"return_5m": Decimal("0.005")},
            candidate_ttl_ms=300_000,
            max_candidates=8,
        ),
        max_snapshot_age_ms=300_000,
        max_portfolio_age_ms=300_000,
        max_calls_per_cycle=8,
        allocation_groups={BTC.value: "crypto", ETH.value: "crypto"},
        max_new_allocation_pct=Decimal("50"),
        max_group_exposure_pct=Decimal("40"),
        fee_buffer_bps=Decimal("10"),
    )


@pytest.fixture
def proposal(evidence):
    return DecisionProposal.model_validate(
        {
            "market_regime": "trend_up",
            "state": "bullish",
            "signals": {"price": 0.5},
            "prediction": {
                "expected_return_bps": 100,
                "confidence": 0.7,
                "uncertainty": 0.3,
                "horizon_minutes": 60,
            },
            "proposed_action": "buy",
            "proposed_notional": {"amount": "300", "currency": "USD"},
            "estimated_cost_bps": "10",
            "evidence_refs": [evidence[0].evidence_id],
            "contradicting_evidence_refs": [evidence[1].evidence_id],
        }
    )


@pytest.fixture
def build_runtime(clock, version, policy, contexts, proposal):
    def build(
        *,
        outputs=None,
        provider=None,
        version_override=None,
        policy_override=None,
        network=None,
        capacity=100,
        telemetry=None,
    ):
        configured = version_override or version
        configured_policy = policy_override or policy
        prompt = analysis_prompt(configured.spec.model_policy.profile)
        quota = ScopeBudget(daily_usd=Decimal("100"), calls_per_minute=100, calls_per_day=1000)
        access = AgentAccess.from_version(
            configured, daily_budget=quota, prompt_keys=(prompt.key,), max_calls=1
        )
        model = provider or MockProvider(
            outputs if outputs is not None else [proposal.model_dump_json()] * 32
        )
        gateway = LocalModelGateway(
            environment="local",
            providers=[model],
            prompts=[prompt],
            agents=[access],
            workspaces={WS: quota},
            routes=[
                Route(
                    profile=ModelProfile.REASON_BALANCED,
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
        runtime = LocalAgentRuntime(
            environment="local",
            gateway=gateway,
            registrations=(
                RuntimeRegistration(agent_version=configured, policy=configured_policy),
            ),
            clock=clock.now,
            capacity=capacity,
            telemetry=telemetry,
            network=network or FrozenNetworkContexts(contexts),
        )
        return runtime, model

    return build
