"""Explicitly synthetic, fail-closed local paper workflow inputs.

This is a user-visible integration rehearsal, not market ingestion, a backtest, a
policy approval, or a trading signal. The global kill remains active for its
isolated account even if a future mock unexpectedly proposes an order.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy import text

from kavrigo_domain import (
    AgentVersion,
    BookTicker,
    DataQuality,
    EvidenceItem,
    FeatureVector,
    FreshnessPolicy,
    FreshnessReport,
    MarketSnapshot,
    Money,
    PortfolioSnapshot,
    Price,
    Quantity,
    RiskLimits,
    RiskPolicy,
    RiskScope,
    TradingMode,
    content_hash,
)
from kavrigo_domain.evidence import EvidenceKind, SourceClass
from kavrigo_domain.snapshot import DataFamily
from kavrigo_paper import PaperConfig, PaperInstrument
from kavrigo_risk import (
    RiskControls,
    RiskExecutionPolicy,
    RiskMarket,
    RiskRegistration,
    policy_hash,
)
from kavrigo_runtime import EvaluationRequest, RuntimePolicy, RuntimeRegistration, ScannerPolicy
from kavrigo_runtime.validation import snapshot_hash
from kavrigo_workflows.accounts import outbox
from kavrigo_workflows.contracts import (
    AccountDefinition,
    AccountRef,
    AgentJob,
    RunDefinition,
    RunRef,
)
from kavrigo_workflows.database import MAX_BYTES, EngineDatabase, encode
from kavrigo_workflows.machine import AccountMachine, DurableError

_NAMESPACE = UUID("cc955b2f-7736-4f50-ae9d-ad448b88591b")
_PLACEHOLDER_IMAGE = "sha256:" + "0" * 64


def rehearsal_run_id(workspace_id: str, key: str) -> str:
    """Stable within a workspace so ambiguous client retries cannot duplicate runs."""
    return "run_" + uuid5(_NAMESPACE, workspace_id + ":" + key).hex


def build_rehearsal(
    version: AgentVersion, *, key: str, at: datetime
) -> tuple[AccountDefinition, RunDefinition]:
    """Build one isolated no-execution scenario from a stored immutable version."""
    spec = version.spec
    instruments = tuple(spec.universe.instruments)
    if (
        spec.mode is not TradingMode.PAPER
        or not 1 <= len(instruments) <= 2
        or any(i.quote != "USD" or i.venue != "SIM" for i in instruments)
    ):
        raise ValueError("rehearsal_requires_one_or_two_simulated_usd_spot_instruments")
    run_id = rehearsal_run_id(version.workspace_id, key)
    evaluation_key = "rehearsal-" + run_id[4:]
    account_id = "rehearsal-" + run_id[4:]
    cash = Money(amount=Decimal("1000"), currency="USD")
    zero = Money.zero("USD")
    portfolio = PortfolioSnapshot(
        workspace_id=version.workspace_id,
        mode=TradingMode.PAPER,
        as_of=at,
        base_currency="USD",
        cash=cash,
        reserved_cash=zero,
        realized_pnl_today=zero,
        unrealized_pnl=zero,
        equity=cash,
        gross_exposure=zero,
        net_exposure=zero,
        peak_equity=cash,
        reconciled_at=at,
    )
    controls = RiskControls(
        workspace_id=version.workspace_id,
        account_id=account_id,
        version=1,
        as_of=at,
        valid_until=at + timedelta(minutes=5),
        account_known=True,
        connectivity_ok=False,
        event_calendar_known=False,
        active_kills=("global",),
        macro_events=(),
        fencing_token=1,
        lease_expires_at=at + timedelta(minutes=5),
    )
    limits = RiskLimits(
        max_gross_exposure_pct=Decimal("0"),
        max_single_asset_exposure_pct=Decimal("0"),
        max_network_exposure_pct=Decimal("0"),
        max_open_positions=0,
        max_daily_loss_pct=Decimal("0"),
        max_drawdown_pct=Decimal("0"),
        min_liquidity_usd=Decimal("1000000"),
        max_spread_bps=0,
        min_order_notional_usd=Decimal("1"),
        max_order_notional_usd=Decimal("1"),
        min_edge_over_cost_bps=10000,
    )
    policies = []
    for n, scope in enumerate((RiskScope.GLOBAL, RiskScope.WORKSPACE, RiskScope.AGENT), 1):
        item = RiskPolicy(
            risk_policy_id=(spec.risk_policy_ref if scope is RiskScope.AGENT else f"rp_{n:032x}"),
            workspace_id=None if scope is RiskScope.GLOBAL else version.workspace_id,
            version=1,
            scope=scope,
            limits=limits,
            freshness=FreshnessPolicy(
                required_families=[DataFamily.TRADES, DataFamily.BOOK],
                max_age_ms={DataFamily.TRADES: 1, DataFamily.BOOK: 1},
            ),
            created_at=at,
            created_by="local-rehearsal",
            content_hash=_PLACEHOLDER_IMAGE,
        )
        policies.append(
            RiskPolicy.model_validate({**item.model_dump(), "content_hash": policy_hash(item)})
        )
    networks = {i.value: "synthetic" for i in instruments}
    registration = RiskRegistration(
        agent_version=version,
        policies=tuple(policies),
        networks=networks,
        execution=RiskExecutionPolicy(
            execution_policy_id=spec.execution_policy_ref,
            version="local-rehearsal-v1",
            fee_bps=Decimal("10"),
            slippage_bps=Decimal("10"),
            notional_increment_usd=Decimal("0.01"),
            max_snapshot_age_ms=1,
            max_portfolio_age_ms=1,
            max_reconciliation_age_ms=1,
            max_market_age_ms=1,
            max_approval_age_ms=1,
        ),
    )
    account = AccountDefinition(
        account_id=account_id,
        initial_portfolio=portfolio,
        controls=controls,
        config=PaperConfig(
            version="local-rehearsal-v1",
            latency_ms=0,
            max_market_age_ms=1,
            instruments=tuple(
                PaperInstrument(
                    instrument_id=i,
                    quantity_step=Decimal("0.000001"),
                    price_tick=Decimal("0.01"),
                    minimum_notional_usd=Decimal("1"),
                    network="synthetic",
                )
                for i in instruments
            ),
        ),
        registrations=(registration,),
    )
    evidence = tuple(
        EvidenceItem(
            evidence_id="ev_" + uuid5(_NAMESPACE, run_id + ":e:" + i.value + ":" + str(n)).hex,
            kind=EvidenceKind.PRICE_TECHNICAL,
            source_class=SourceClass.DERIVED_FEATURE,
            provider="kavrigo-synthetic",
            summary=summary,
            instruments=[i],
            observed_at=at,
            ingested_at=at,
            source_ref="synthetic-rehearsal-v1",
            content_hash=content_hash(summary),
            quality=1.0,
            confidence=0.0,
            is_contradictory_candidate=n % 2 == 1,
            license_ref="self-authored-synthetic",
        )
        for i in instruments
        for n, summary in enumerate(
            (
                "Synthetic upward feature; no market observation.",
                "Synthetic contradiction; no market observation.",
            )
        )
    )
    features = [
        FeatureVector(
            instrument_id=i,
            feature_set_version=version.feature_set_version,
            values={"return_5m": Decimal("0.02")},
            content_hash=content_hash(
                {
                    "instrument_id": i.value,
                    "feature_set_version": version.feature_set_version,
                    "values": {"return_5m": Decimal("0.02")},
                }
            ),
        )
        for i in instruments
    ]
    snapshot = MarketSnapshot(
        snapshot_id="snap_" + run_id[4:],
        as_of=at,
        created_at=at,
        instruments=list(instruments),
        features=features,
        evidence_refs=[e.evidence_id for e in evidence],
        quality=DataQuality(
            score=1.0,
            freshness=FreshnessReport(age_ms={}),
            notes=["synthetic_rehearsal_only", "not_live_market_data"],
        ),
        content_hash=_PLACEHOLDER_IMAGE,
    )
    snapshot = MarketSnapshot.model_validate(
        {**snapshot.model_dump(mode="python"), "content_hash": snapshot_hash(snapshot)}
    )
    runtime = RuntimeRegistration(
        agent_version=version,
        policy=RuntimePolicy(
            version="local-rehearsal-v1",
            code_version="local-rehearsal-v1",
            code_image_digest=_PLACEHOLDER_IMAGE,
            scanner=ScannerPolicy(
                absolute_thresholds={"return_5m": Decimal("0.001")},
                candidate_ttl_ms=60000,
                max_candidates=2,
            ),
            max_snapshot_age_ms=60000,
            max_portfolio_age_ms=60000,
            max_calls_per_cycle=2,
            allocation_groups=networks,
            max_new_allocation_pct=Decimal("0"),
            max_group_exposure_pct=Decimal("0"),
            fee_buffer_bps=Decimal("10"),
        ),
    )
    markets = {
        i.value: RiskMarket(
            book=BookTicker(
                instrument_id=i,
                bid_price=Price(value=Decimal("99.90"), base=i.base, quote="USD"),
                ask_price=Price(value=Decimal("100.10"), base=i.base, quote="USD"),
                bid_size=Quantity(value=Decimal("100"), asset=i.base),
                ask_size=Quantity(value=Decimal("100"), asset=i.base),
                venue_time=at,
                received_at=at,
            ),
            liquidity_usd=Decimal("0"),
            observed_at=at,
        )
        for i in instruments
    }
    run = RunDefinition(
        workspace_id=version.workspace_id,
        run_id=run_id,
        job=AgentJob(
            account=AccountRef(workspace_id=version.workspace_id, account_id=account_id),
            generation=1,
            registration=runtime,
            evaluation=EvaluationRequest(
                workspace_id=version.workspace_id,
                agent_version_id=version.agent_version_id,
                idempotency_key=evaluation_key,
                horizon_minutes=spec.analysis.horizons_minutes[0],
                snapshot=snapshot,
                portfolio=portfolio,
                evidence=evidence,
            ),
            markets=markets,
        ),
    )
    return account, run


async def persist_rehearsal(
    database: EngineDatabase, version: AgentVersion, *, key: str, at: datetime
) -> tuple[RunRef, bool]:
    """Atomically store the isolated account, frozen run and dispatch event.

    A retry uses the exact original run. It never refreshes an old snapshot under
    the same key, which would turn one high-impact command into a different run.
    """
    run_id = rehearsal_run_id(version.workspace_id, key)
    async with database.transaction(version.workspace_id) as connection:
        await connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:run, 0))"), {"run": run_id}
        )
        existing = (
            (
                await connection.execute(
                    text("""SELECT definition,input_hash FROM kavrigo.engine_runs
                    WHERE workspace_id=:ws AND run_id=:run"""),
                    {"ws": version.workspace_id, "run": run_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            saved = RunDefinition.model_validate_json(existing["definition"])
            if (
                not isinstance(saved.job, AgentJob)
                or saved.job.registration.agent_version.agent_version_id != version.agent_version_id
                or saved.job.evaluation.idempotency_key != "rehearsal-" + run_id[4:]
                or content_hash(saved) != existing["input_hash"]
            ):
                raise DurableError("rehearsal_idempotency_conflict")
            return RunRef(
                workspace_id=version.workspace_id, run_id=run_id, input_hash=existing["input_hash"]
            ), True
        account, run = build_rehearsal(version, key=key, at=at)
        machine = AccountMachine(account)
        receipt = machine.initial_receipt()
        account_json, receipt_json = encode(account), encode(receipt)
        size = len((account_json + receipt_json).encode("utf-8"))
        if size > MAX_BYTES:
            raise DurableError("account_capacity_exhausted")
        await connection.execute(
            text("""INSERT INTO kavrigo.engine_accounts
            (workspace_id,account_id,definition,definition_hash,head_sequence,head_hash,head_receipt,bytes_used)
            VALUES (:ws,:account,:definition,:hash,0,:hash,:receipt,:size)"""),
            {
                "ws": version.workspace_id,
                "account": account.account_id,
                "definition": account_json,
                "hash": content_hash(account),
                "receipt": receipt_json,
                "size": size,
            },
        )
        ref = RunRef(workspace_id=version.workspace_id, run_id=run_id, input_hash=content_hash(run))
        await connection.execute(
            text("""INSERT INTO kavrigo.engine_runs
            (workspace_id,run_id,definition,input_hash,created_at)
            VALUES (:ws,:run,:definition,:hash,clock_timestamp())"""),
            {
                "ws": ref.workspace_id,
                "run": ref.run_id,
                "definition": encode(run),
                "hash": ref.input_hash,
            },
        )
        await outbox(connection, ref.workspace_id, "run.queued", ref.run_id, encode(ref))
        return ref, False
