"""The Nautilus adapter against a real NautilusTrader engine.

These construct an actual ``BacktestEngine`` rather than a mock: the point of ADR 0012 was to
get a real simulator's fill semantics, and a test that never touches it would not notice a
version whose API had moved underneath us.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from kavrigo_backtest import (
    BAR_PARQUET_SCHEMA,
    BacktestBar,
    BacktestRunConfig,
    CostModel,
    DatasetManifest,
    DatasetSource,
    FeeSchedule,
    InlineBarDataset,
    LatencyModel,
    LocalParquetBarCatalog,
    LongOnlyEmaStrategy,
    ParquetBarDatasetRef,
    ReferenceRiskReplay,
    SlippageModel,
    TimeBasis,
    bar_dataset_hash,
    parquet_bytes_hash,
)
from kavrigo_domain import (
    AgentSpec,
    AgentVersion,
    ApprovalStatus,
    DataPack,
    FreshnessPolicy,
    InstrumentId,
    ModelPolicy,
    Money,
    RiskExecutionPolicy,
    RiskLimits,
    RiskPolicy,
    RiskScope,
    ScheduleConfig,
    TradingMode,
    UniverseConfig,
    content_hash,
)
from kavrigo_domain.snapshot import DataFamily
from kavrigo_nautilus import NautilusBacktestAdapter
from kavrigo_workflows.accounts import AccountRepository
from kavrigo_workflows.activities import EngineActivities
from kavrigo_workflows.contracts import BacktestJob, RunDefinition, StageRef, StageRequest
from kavrigo_workflows.dispatch import start_run, workflow_id
from kavrigo_workflows.runs import RunRepository

from .conftest import WS
from .test_workflows_integration import replay, worker
from .test_workflows_integration import temporal_client as temporal_client

START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 2, 1, tzinfo=UTC)
HASH = "sha256:" + "ab" * 32


def oid(prefix: str, n: int = 1) -> str:
    return f"{prefix}_{n:032x}"


def _manifest(**overrides: object) -> DatasetManifest:
    values: dict[str, object] = {
        "manifest_id": oid("ds"),
        "created_at": END,
        "period_start": START,
        "period_end": END,
        "time_basis": TimeBasis.INGESTED_AT,
        "sources": [
            DatasetSource(
                provider="binance",
                venue="BINANCE",
                dataset="kavrigo.market_trades",
                row_count=1000,
                content_hash=HASH,
                first_event_time=START,
                last_event_time=END - timedelta(minutes=1),
                last_ingested_at=END - timedelta(seconds=30),
                license_ref="binance-public-tos",
            )
        ],
        "instruments": ["BTC-USDT.BINANCE", "ETH-USDT.BINANCE"],
        "feature_set_version": "v1",
    }
    values.update(overrides)
    return DatasetManifest(**values)  # type: ignore[arg-type]


def _config(**overrides: object) -> BacktestRunConfig:
    spec = AgentSpec(
        name="btc-eth-baseline",
        universe=UniverseConfig(
            instruments=[
                InstrumentId.parse("BTC-USDT.BINANCE"),
                InstrumentId.parse("ETH-USDT.BINANCE"),
            ]
        ),
        schedule=ScheduleConfig(decision_interval_seconds=900),
        data_packs=[DataPack.MARKET_MICROSTRUCTURE],
        model_policy=ModelPolicy(max_cost_per_decision_usd=Decimal("0.10")),
        risk_policy_ref=oid("rp"),
        execution_policy_ref=oid("ep"),
    )
    values: dict[str, object] = {
        "run_id": oid("run"),
        "workspace_id": oid("ws"),
        "agent_version_id": oid("av"),
        "spec": spec,
        "dataset": _manifest(),
        "costs": CostModel(
            fees=FeeSchedule(venue="BINANCE", maker_bps=Decimal("1"), taker_bps=Decimal("10")),
            slippage=SlippageModel(spread_crossing_bps=Decimal("2")),
            latency=LatencyModel(decision_to_venue_ms=50, venue_ack_ms=10),
        ),
        "starting_balance": Money(amount=Decimal("100000"), currency="USDT"),
        "random_seed": 42,
    }
    values.update(overrides)
    return BacktestRunConfig(**values)  # type: ignore[arg-type]


def _inline_config(**overrides: object) -> BacktestRunConfig:
    instrument = InstrumentId.parse("BTC-USDT.BINANCE")
    prices = [
        Decimal(100 + (i if i < 15 else 30 - i if i < 30 else i - 30 if i < 45 else 60 - i))
        for i in range(60)
    ]
    bars = tuple(
        BacktestBar(
            instrument_id=instrument,
            interval_seconds=900,
            open=price,
            high=price + Decimal(1),
            low=price - Decimal(1),
            close=price + Decimal("0.5"),
            volume=Decimal("1000.000000"),
            event_time=START + timedelta(minutes=15 * index),
            ingested_at=START + timedelta(minutes=15 * index, seconds=1),
        )
        for index, price in enumerate(prices)
    )
    inline_data = InlineBarDataset(bars=bars, content_hash=bar_dataset_hash(bars))
    period_end = START + timedelta(days=1)
    dataset = DatasetManifest(
        manifest_id=oid("ds", 2),
        created_at=period_end,
        period_start=START,
        period_end=period_end,
        time_basis=TimeBasis.INGESTED_AT,
        sources=[
            DatasetSource(
                provider="deterministic-fixture",
                venue="BINANCE",
                dataset="inline-bars-v1",
                row_count=len(bars),
                content_hash=inline_data.content_hash,
                first_event_time=bars[0].event_time,
                last_event_time=bars[-1].event_time,
                last_ingested_at=bars[-1].ingested_at,
                license_ref="self-authored-fixture-v1",
            )
        ],
        instruments=[instrument.value],
        feature_set_version="v1",
        notes="Deterministic synthetic shape for durable workflow validation only.",
    )
    spec = AgentSpec(
        name="btc-reference-fixture",
        universe=UniverseConfig(instruments=[instrument]),
        schedule=ScheduleConfig(decision_interval_seconds=900),
        data_packs=[DataPack.PRICE_TECHNICAL],
        model_policy=ModelPolicy(max_cost_per_decision_usd=Decimal("0.10")),
        risk_policy_ref=oid("rp"),
        execution_policy_ref=oid("ep"),
    )
    return _config(
        spec=spec,
        dataset=dataset,
        benchmark_instrument=instrument.value,
        inline_data=inline_data,
        strategy=LongOnlyEmaStrategy(trade_notional=Money(amount=Decimal("100"), currency="USDT")),
        **overrides,
    )


def _catalog_config(tmp_path: Path, **overrides: object) -> BacktestRunConfig:
    inline = _inline_config()
    assert inline.inline_data is not None
    target = tmp_path / "fixtures" / "btc.parquet"
    target.parent.mkdir()
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "instrument_id": bar.instrument_id.value,
                    "interval_seconds": bar.interval_seconds,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "event_time": bar.event_time,
                    "ingested_at": bar.ingested_at,
                }
                for bar in inline.inline_data.bars
            ],
            schema=BAR_PARQUET_SCHEMA,
        ),
        target,
    )
    reference = ParquetBarDatasetRef(
        object_key="fixtures/btc.parquet",
        content_hash=parquet_bytes_hash(target.read_bytes()),
        row_count=len(inline.inline_data.bars),
        instrument_id=inline.spec.universe.instruments[0],
        interval_seconds=inline.inline_data.bars[0].interval_seconds,
    )
    source = inline.dataset.sources[0].model_copy(
        update={"dataset": "local-parquet-bars-v1", "content_hash": reference.content_hash}
    )
    values = inline.model_dump(mode="python")
    values.update(
        inline_data=None,
        catalog_data=reference,
        dataset=inline.dataset.model_copy(update={"sources": [source]}),
        **overrides,
    )
    return BacktestRunConfig.model_validate(values)


def _risk_config(*, workspace_id: str, run_id: str) -> BacktestRunConfig:
    inline = _inline_config(workspace_id=workspace_id, run_id=run_id)
    assert inline.inline_data is not None
    instrument = InstrumentId.parse("BTC-USD.SIM")
    bars = tuple(
        bar.model_copy(update={"instrument_id": instrument}) for bar in inline.inline_data.bars
    )
    inline_data = InlineBarDataset(bars=bars, content_hash=bar_dataset_hash(bars))
    source = inline.dataset.sources[0].model_copy(
        update={
            "provider": "kavrigo-synthetic",
            "venue": "SIM",
            "content_hash": inline_data.content_hash,
            "license_ref": "self-authored-reference-risk-v1",
        }
    )
    dataset = inline.dataset.model_copy(
        update={"sources": [source], "instruments": [instrument.value]}
    )
    spec = inline.spec.model_copy(
        update={
            "mode": TradingMode.BACKTEST,
            "universe": UniverseConfig(instruments=[instrument]),
        }
    )
    version = AgentVersion(
        agent_version_id=inline.agent_version_id,
        agent_id=oid("ag"),
        workspace_id=workspace_id,
        version=1,
        spec=spec,
        spec_hash=content_hash(spec),
        prompt_version_id=oid("pv"),
        prompt_hash=HASH,
        feature_set_version="v1",
        created_at=START - timedelta(days=1),
        created_by="reference-risk-fixture",
        approval_status=ApprovalStatus.APPROVED,
        approved_environments=["local"],
    )
    limits = RiskLimits(
        max_gross_exposure_pct=Decimal("80"),
        max_single_asset_exposure_pct=Decimal("80"),
        max_network_exposure_pct=Decimal("80"),
        max_open_positions=1,
        max_daily_loss_pct=Decimal("20"),
        max_drawdown_pct=Decimal("30"),
        min_liquidity_usd=Decimal("1000"),
        max_spread_bps=50,
        min_order_notional_usd=Decimal("1"),
        max_order_notional_usd=Decimal("1000"),
        min_edge_over_cost_bps=5,
    )
    policies = []
    for number, scope in enumerate((RiskScope.GLOBAL, RiskScope.WORKSPACE, RiskScope.AGENT), 1):
        policy = RiskPolicy(
            risk_policy_id=spec.risk_policy_ref
            if scope is RiskScope.AGENT
            else oid("rp", number + 1),
            workspace_id=None if scope is RiskScope.GLOBAL else workspace_id,
            version=1,
            scope=scope,
            limits=limits,
            freshness=FreshnessPolicy(
                required_families=[DataFamily.CANDLES],
                max_age_ms={DataFamily.CANDLES: 1},
            ),
            created_at=START - timedelta(days=1),
            created_by="reference-risk-fixture",
            content_hash=HASH,
        )
        policies.append(
            policy.model_copy(
                update={
                    "content_hash": content_hash(
                        policy.model_dump(mode="python", exclude={"content_hash"})
                    )
                }
            )
        )
    costs = inline.costs.model_copy(
        update={"fees": inline.costs.fees.model_copy(update={"venue": "SIM"})}
    )
    replay_config = ReferenceRiskReplay(
        agent_version=version,
        policies=tuple(policies),
        execution=RiskExecutionPolicy(
            execution_policy_id=spec.execution_policy_ref,
            version="reference-risk-v1",
            fee_bps=costs.fees.taker_bps,
            slippage_bps=costs.slippage.slippage_bps(),
            notional_increment_usd=Decimal("0.000000000001"),
            max_snapshot_age_ms=5000,
            max_portfolio_age_ms=5000,
            max_reconciliation_age_ms=5000,
            max_market_age_ms=5000,
            max_approval_age_ms=5000,
        ),
        networks={instrument.value: "crypto"},
        account_id="reference-backtest",
        expected_edge_bps=Decimal("100"),
    )
    values = inline.model_dump(mode="python")
    values.update(
        spec=spec,
        dataset=dataset,
        costs=costs,
        starting_balance=Money(amount=Decimal("100000"), currency="USD"),
        benchmark_instrument=instrument.value,
        inline_data=inline_data,
        strategy=LongOnlyEmaStrategy(trade_notional=Money(amount=Decimal("100"), currency="USD")),
        risk_replay=replay_config,
    )
    return BacktestRunConfig.model_validate(values)


pytestmark = pytest.mark.integration


async def test_nautilus_workflow_records_artifact_but_refuses_empty_research(
    engine_database, temporal_client
):
    adapter = NautilusBacktestAdapter()
    config = _config(workspace_id=WS, run_id="run_" + uuid4().hex)
    bundle = adapter.bundle_for(
        config,
        spec_hash=content_hash(config.spec),
        prompt_hash=HASH,
        feature_manifest_hash=HASH,
        model_profile="reason_balanced",
        resolved_model_identifier="mock-v1",
        container_image_digest=HASH,
        code_version="fixture-v1",
    )
    runs = RunRepository(engine_database)
    ref = await runs.create(
        RunDefinition(
            workspace_id=WS, run_id=config.run_id, job=BacktestJob(config=config, bundle=bundle)
        )
    )
    activities = EngineActivities(runs, AccountRepository(engine_database), backtest=adapter)
    queue = uuid4().hex
    async with worker(temporal_client, activities, queue):
        await start_run(temporal_client, runs, ref, queue)
        handle = temporal_client.get_workflow_handle(workflow_id(ref), result_type=StageRef)
        assert (await asyncio.wait_for(handle.result(), 30)).status == "refused"
    async with engine_database.transaction(WS) as connection:
        saved = await runs.stage(connection, ref, "backtest")
        output = json.loads(saved["output"])
        assert output["decisions_evaluated"] == 0
        assert output["bundle"] == bundle.model_dump(mode="json")
        receipt = runs.stage_ref(ref, saved)
    assert await activities._stage(StageRequest(run=ref, stage="backtest")) == receipt
    await replay(handle)


async def test_nautilus_workflow_completes_a_meaningful_reference_run(
    engine_database, temporal_client
):
    adapter = NautilusBacktestAdapter()
    config = _inline_config(workspace_id=WS, run_id="run_" + uuid4().hex)
    bundle = adapter.bundle_for(
        config,
        spec_hash=content_hash(config.spec),
        prompt_hash=HASH,
        feature_manifest_hash=HASH,
        model_profile="reason_balanced",
        resolved_model_identifier="mock-v1",
        container_image_digest=HASH,
        code_version="fixture-v1",
    )
    runs = RunRepository(engine_database)
    ref = await runs.create(
        RunDefinition(
            workspace_id=WS, run_id=config.run_id, job=BacktestJob(config=config, bundle=bundle)
        )
    )
    activities = EngineActivities(runs, AccountRepository(engine_database), backtest=adapter)
    queue = uuid4().hex
    async with worker(temporal_client, activities, queue):
        await start_run(temporal_client, runs, ref, queue)
        handle = temporal_client.get_workflow_handle(workflow_id(ref), result_type=StageRef)
        assert (await asyncio.wait_for(handle.result(), 30)).status == "completed"
    async with engine_database.transaction(WS) as connection:
        saved = await runs.stage(connection, ref, "backtest")
        output = json.loads(saved["output"])
        assert output["decisions_evaluated"] > 0
        assert output["orders_submitted"] > 0
        assert output["metrics"]["trade_count"] > 0
        assert output["metrics"]["benchmark_return"] is not None
        assert output["limitations"] == sorted(output["limitations"])
        receipt = runs.stage_ref(ref, saved)
    assert await activities._stage(StageRequest(run=ref, stage="backtest")) == receipt
    await replay(handle)


async def test_nautilus_workflow_persists_deterministic_risk_replay_receipts(
    engine_database, temporal_client
):
    adapter = NautilusBacktestAdapter()
    config = _risk_config(workspace_id=WS, run_id="run_" + uuid4().hex)
    assert config.risk_replay is not None
    version = config.risk_replay.agent_version
    bundle = adapter.bundle_for(
        config,
        spec_hash=version.spec_hash,
        prompt_hash=version.prompt_hash,
        feature_manifest_hash=HASH,
        model_profile="reference_strategy",
        resolved_model_identifier="deterministic-reference-no-model",
        container_image_digest=HASH,
        code_version="risk-replay-fixture-v1",
    )
    runs = RunRepository(engine_database)
    ref = await runs.create(
        RunDefinition(
            workspace_id=WS, run_id=config.run_id, job=BacktestJob(config=config, bundle=bundle)
        )
    )
    activities = EngineActivities(runs, AccountRepository(engine_database), backtest=adapter)
    queue = uuid4().hex
    async with worker(temporal_client, activities, queue):
        await start_run(temporal_client, runs, ref, queue)
        handle = temporal_client.get_workflow_handle(workflow_id(ref), result_type=StageRef)
        assert (await asyncio.wait_for(handle.result(), 30)).status == "completed"
    async with engine_database.transaction(WS) as connection:
        saved = await runs.stage(connection, ref, "backtest")
        output = json.loads(saved["output"])
        assert output["risk_evaluations"] == 4
        assert output["risk_approvals"] == 4
        assert output["orders_rejected_by_risk"] == 0
        assert output["orders_submitted"] == 4
        assert output["risk_replay_hash"] == config.risk_replay.replay_hash
        assert "deterministic_risk_policy_not_replayed" not in output["limitations"]
        receipt = runs.stage_ref(ref, saved)
    assert await activities._stage(StageRequest(run=ref, stage="backtest")) == receipt
    await replay(handle)


async def test_nautilus_workflow_resolves_a_frozen_parquet_catalog_object(
    engine_database, temporal_client, tmp_path: Path
):
    config = _catalog_config(tmp_path, workspace_id=WS, run_id="run_" + uuid4().hex)
    adapter = NautilusBacktestAdapter(catalog=LocalParquetBarCatalog(tmp_path))
    bundle = adapter.bundle_for(
        config,
        spec_hash=content_hash(config.spec),
        prompt_hash=HASH,
        feature_manifest_hash=HASH,
        model_profile="reference_strategy",
        resolved_model_identifier="no-model",
        container_image_digest=HASH,
        code_version="catalog-fixture-v1",
    )
    runs = RunRepository(engine_database)
    ref = await runs.create(
        RunDefinition(
            workspace_id=WS, run_id=config.run_id, job=BacktestJob(config=config, bundle=bundle)
        )
    )
    activities = EngineActivities(runs, AccountRepository(engine_database), backtest=adapter)
    queue = uuid4().hex
    async with worker(temporal_client, activities, queue):
        await start_run(temporal_client, runs, ref, queue)
        handle = temporal_client.get_workflow_handle(workflow_id(ref), result_type=StageRef)
        assert (await asyncio.wait_for(handle.result(), 30)).status == "completed"
    async with engine_database.transaction(WS) as connection:
        saved = await runs.stage(connection, ref, "backtest")
        output = json.loads(saved["output"])
        assert output["decisions_evaluated"] == 53
        assert output["orders_submitted"] == 4
        assert "local_parquet_catalog_not_production_snapshot" in output["limitations"]
    await replay(handle)
