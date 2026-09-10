"""The Nautilus adapter against a real NautilusTrader engine.

These construct an actual ``BacktestEngine`` rather than a mock: the point of ADR 0012 was to
get a real simulator's fill semantics, and a test that never touches it would not notice a
version whose API had moved underneath us.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from kavrigo_backtest import (
    BacktestRunConfig,
    CostModel,
    DatasetManifest,
    DatasetSource,
    FeeSchedule,
    LatencyModel,
    SlippageModel,
    TimeBasis,
)
from kavrigo_domain import (
    AgentSpec,
    DataPack,
    InstrumentId,
    ModelPolicy,
    Money,
    ScheduleConfig,
    UniverseConfig,
    content_hash,
)
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
