from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from kavrigo_domain import (
    AgentDecision,
    AgentSpec,
    AgentVersion,
    ApprovalStatus,
    BookTicker,
    DataPack,
    DataQuality,
    EvidenceItem,
    EvidenceRequirements,
    FreshnessPolicy,
    FreshnessReport,
    InstrumentId,
    MarketSnapshot,
    ModelPolicy,
    Money,
    OrderIntent,
    OrderSide,
    OrderType,
    PortfolioSnapshot,
    Price,
    Quantity,
    RiskLimits,
    RiskPolicy,
    RiskScope,
    ScheduleConfig,
    TradingMode,
    UniverseConfig,
    content_hash,
)
from kavrigo_domain.evidence import EvidenceKind, SourceClass
from kavrigo_domain.snapshot import DataFamily
from kavrigo_risk import (
    LocalRiskSession,
    RiskControls,
    RiskExecutionPolicy,
    RiskMarket,
    RiskRegistration,
    RiskRequest,
    policy_hash,
)
from kavrigo_runtime.contracts import Allocation
from kavrigo_runtime.validation import snapshot_hash

WS = "ws_" + "1" * 32
AV = "av_" + "2" * 32
BTC = InstrumentId.parse("BTC-USD.SIM")
ETH = InstrumentId.parse("ETH-USD.SIM")
HASH = "sha256:" + "0" * 64


def oid(prefix, number):
    return f"{prefix}_{number:032x}"


def money(amount):
    return Money(amount=Decimal(str(amount)), currency="USD")


def change(model, **updates):
    return type(model).model_validate({**model.model_dump(mode="python"), **updates})


def seal(policy):
    return change(policy, content_hash=policy_hash(policy))


class Clock:
    def __init__(self):
        self.now = datetime.now(UTC)

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def portfolio(clock):
    return PortfolioSnapshot(
        workspace_id=WS,
        mode=TradingMode.PAPER,
        as_of=clock(),
        base_currency="USD",
        cash=money(1000),
        reserved_cash=money(0),
        realized_pnl_today=money(0),
        unrealized_pnl=money(0),
        equity=money(1000),
        gross_exposure=money(0),
        net_exposure=money(0),
        peak_equity=money(1000),
        reconciled_at=clock(),
    )


@pytest.fixture
def controls(clock):
    return RiskControls(
        workspace_id=WS,
        account_id="paper-account-one",
        version=1,
        as_of=clock(),
        valid_until=clock() + timedelta(minutes=5),
        account_known=True,
        connectivity_ok=True,
        event_calendar_known=True,
        active_kills=(),
        macro_events=(),
        fencing_token=1,
        lease_expires_at=clock() + timedelta(minutes=5),
    )


@pytest.fixture
def registration(clock):
    spec = AgentSpec(
        name="risk-fixture",
        universe=UniverseConfig(instruments=[BTC, ETH]),
        schedule=ScheduleConfig(decision_interval_seconds=60),
        data_packs=[DataPack.NEWS, DataPack.PRICE_TECHNICAL],
        model_policy=ModelPolicy(max_cost_per_decision_usd=Decimal("1")),
        evidence=EvidenceRequirements(min_evidence_items=2),
        risk_policy_ref=oid("rp", 3),
        execution_policy_ref=oid("ep", 1),
    )
    version = AgentVersion(
        agent_version_id=AV,
        agent_id=oid("ag", 1),
        workspace_id=WS,
        version=1,
        spec=spec,
        spec_hash=content_hash(spec),
        prompt_version_id=oid("pv", 1),
        prompt_hash=HASH,
        feature_set_version="v1",
        created_at=clock() - timedelta(days=1),
        created_by="fixture",
        approval_status=ApprovalStatus.APPROVED,
        approved_environments=["local"],
    )
    limits = RiskLimits(
        max_gross_exposure_pct=Decimal("50"),
        max_single_asset_exposure_pct=Decimal("30"),
        max_network_exposure_pct=Decimal("40"),
        max_open_positions=2,
        max_daily_loss_pct=Decimal("2"),
        max_drawdown_pct=Decimal("8"),
        min_liquidity_usd=Decimal("10000"),
        max_spread_bps=30,
        min_order_notional_usd=Decimal("1"),
        max_order_notional_usd=Decimal("400"),
        min_edge_over_cost_bps=5,
    )
    policies = tuple(
        seal(
            RiskPolicy(
                risk_policy_id=oid("rp", n),
                workspace_id=None if scope is RiskScope.GLOBAL else WS,
                version=1,
                scope=scope,
                limits=limits,
                freshness=FreshnessPolicy(
                    required_families=[DataFamily.TRADES, DataFamily.BOOK],
                    max_age_ms={DataFamily.TRADES: 5000, DataFamily.BOOK: 2000},
                ),
                created_at=clock() - timedelta(days=1),
                created_by="fixture",
                content_hash=HASH,
            )
        )
        for n, scope in enumerate((RiskScope.GLOBAL, RiskScope.WORKSPACE, RiskScope.AGENT), 1)
    )
    return RiskRegistration(
        agent_version=version,
        policies=policies,
        networks={BTC.value: "crypto", ETH.value: "crypto"},
        execution=RiskExecutionPolicy(
            execution_policy_id=oid("ep", 1),
            version="fixture-v1",
            fee_bps=Decimal("10"),
            slippage_bps=Decimal("10"),
            notional_increment_usd=Decimal("0.01"),
            max_snapshot_age_ms=5000,
            max_portfolio_age_ms=5000,
            max_reconciliation_age_ms=5000,
            max_market_age_ms=2000,
            max_approval_age_ms=10000,
        ),
    )


@pytest.fixture
def make_request(clock):
    def build(number=1, amount="100", instrument=BTC, action="buy"):
        evidence = tuple(
            EvidenceItem(
                evidence_id=oid("ev", n),
                kind=EvidenceKind.NEWS,
                source_class=SourceClass.OFFICIAL_PRIMARY,
                provider="synthetic-fixture",
                summary=text,
                observed_at=clock() - timedelta(seconds=1),
                ingested_at=clock() - timedelta(seconds=1),
                content_hash=content_hash(text),
                quality=0.9,
                confidence=0.8,
                license_ref="synthetic",
            )
            for n, text in [(1, "Liquidity improved."), (2, "An outage remains possible.")]
        )
        snapshot = MarketSnapshot(
            snapshot_id=oid("snap", number),
            as_of=clock(),
            created_at=clock(),
            instruments=[BTC, ETH],
            evidence_refs=[e.evidence_id for e in evidence],
            quality=DataQuality(
                score=0.9,
                freshness=FreshnessReport(age_ms={DataFamily.TRADES: 0, DataFamily.BOOK: 0}),
            ),
            content_hash=HASH,
        )
        snapshot = change(snapshot, content_hash=snapshot_hash(snapshot))
        decision = AgentDecision.model_validate(
            {
                "decision_id": oid("dec", number),
                "workspace_id": WS,
                "agent_version_id": AV,
                "snapshot_id": snapshot.snapshot_id,
                "instrument_id": instrument,
                "decided_at": clock(),
                "market_regime": "trend_up",
                "state": "bullish",
                "signals": {},
                "prediction": {
                    "expected_return_bps": 100 if action == "buy" else -100,
                    "confidence": 0.7,
                    "uncertainty": 0.3,
                    "horizon_minutes": 60,
                },
                "proposed_action": action,
                "proposed_notional": money(amount),
                "evidence_refs": [evidence[0].evidence_id],
                "contradicting_evidence_refs": [evidence[1].evidence_id],
                "estimated_cost_bps": "0",
            }
        )

        def price(value):
            return Price(value=Decimal(value), base=instrument.base, quote="USD")

        return RiskRequest(
            intent=OrderIntent(
                order_intent_id=oid("oi", number),
                decision_id=decision.decision_id,
                workspace_id=WS,
                agent_version_id=AV,
                instrument_id=instrument,
                mode=TradingMode.PAPER,
                side=OrderSide.BUY if action == "buy" else OrderSide.SELL,
                order_type=OrderType.MARKET,
                notional=money(amount),
                idempotency_key=f"risk-request-{number}",
                created_at=clock(),
                expires_at=clock() + timedelta(minutes=1),
                estimated_cost_bps=Decimal("0"),
            ),
            decision=decision,
            allocation=Allocation(
                decision_id=decision.decision_id,
                instrument_id=instrument,
                requested_notional=money(amount),
                allocated_notional=money(amount),
                reason_codes=("allocated",),
            ),
            snapshot=snapshot,
            evidence=evidence,
            market=RiskMarket(
                book=BookTicker(
                    instrument_id=instrument,
                    bid_price=price("99.9"),
                    ask_price=price("100.1"),
                    bid_size=Quantity(value="1000", asset=instrument.base),
                    ask_size=Quantity(value="1000", asset=instrument.base),
                    venue_time=clock(),
                    received_at=clock(),
                ),
                liquidity_usd=Decimal("100000"),
                observed_at=clock(),
            ),
        )

    return build


@pytest.fixture
def build_session(clock, portfolio, controls, registration):
    def build(**overrides):
        return LocalRiskSession(
            **{
                "environment": "local",
                "portfolio": portfolio,
                "controls": controls,
                "registrations": (registration,),
                "clock": clock,
                **overrides,
            }
        )

    return build


@pytest.fixture
def paper_config():
    from kavrigo_paper import PaperConfig, PaperInstrument

    return PaperConfig(
        version="durable-fixture-v1",
        latency_ms=0,
        max_market_age_ms=2000,
        instruments=tuple(
            PaperInstrument(
                instrument_id=i,
                quantity_step="0.0001",
                price_tick="0.0001",
                minimum_notional_usd="1",
                network="crypto",
            )
            for i in (BTC, ETH)
        ),
    )


@pytest.fixture
def definition(portfolio, controls, registration, paper_config):
    from uuid import uuid4

    from kavrigo_workflows.contracts import AccountDefinition

    controls = change(controls, account_id="test-" + uuid4().hex)
    return AccountDefinition(
        account_id=controls.account_id,
        initial_portfolio=portfolio,
        config=paper_config,
        controls=controls,
        registrations=(registration,),
    )


def observation(clock, sequence=1, quantity="100", instrument=BTC):
    from kavrigo_paper import PaperBook, PaperLevel

    return PaperBook(
        instrument_id=instrument,
        sequence=sequence,
        event_time=clock(),
        received_at=clock(),
        bids=(PaperLevel(price="99.9", quantity=quantity),),
        asks=(PaperLevel(price="100.1", quantity=quantity),),
    )


@pytest.fixture
async def engine_database():
    import os

    from sqlalchemy import text

    from kavrigo_workflows.database import EngineDatabase

    dsn = os.getenv(
        "TEST_POSTGRES_DSN",
        "postgresql+asyncpg://kavrigo_app:kavrigo_local_dev@localhost:55432/kavrigo_test",
    )
    database = EngineDatabase(dsn)
    try:
        try:
            async with database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:
            pytest.skip("PostgreSQL unavailable; run the local stack")
        # Reachable but unmigrated is a failure, never a silently skipped integration.
        async with database.transaction(WS) as connection:
            await connection.execute(text("SELECT 1 FROM kavrigo.engine_accounts LIMIT 1"))
            await connection.execute(
                text("""INSERT INTO kavrigo.workspaces(workspace_id,name,slug)
                VALUES (:ws,'Engine fixtures',:slug) ON CONFLICT DO NOTHING"""),
                {"ws": WS, "slug": "engine-" + WS[3:]},
            )
        yield database
    finally:
        await database.close()
