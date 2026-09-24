"""The Nautilus adapter against a real NautilusTrader engine.

These construct an actual ``BacktestEngine`` rather than a mock: the point of ADR 0012 was to
get a real simulator's fill semantics, and a test that never touches it would not notice a
version whose API had moved underneath us.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import nautilus_trader
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

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
    ReproducibilityBundle,
    RunStatus,
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


def _inline_config() -> BacktestRunConfig:
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
        notes="Deterministic synthetic shape for adapter and workflow validation only.",
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
    )


def _catalog_config(tmp_path: Path) -> BacktestRunConfig:
    inline = _inline_config()
    assert inline.inline_data is not None
    target = tmp_path / "fixtures" / "btc.parquet"
    target.parent.mkdir()
    table = pa.Table.from_pylist(
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
    )
    pq.write_table(table, target)
    reference = ParquetBarDatasetRef(
        object_key="fixtures/btc.parquet",
        content_hash=parquet_bytes_hash(target.read_bytes()),
        row_count=len(inline.inline_data.bars),
        instrument_id=inline.spec.universe.instruments[0],
        interval_seconds=inline.inline_data.bars[0].interval_seconds,
    )
    source = inline.dataset.sources[0].model_copy(
        update={
            "dataset": "local-parquet-bars-v1",
            "content_hash": reference.content_hash,
        }
    )
    values = inline.model_dump(mode="python")
    values.update(
        inline_data=None,
        catalog_data=reference,
        dataset=inline.dataset.model_copy(update={"sources": [source]}),
    )
    return BacktestRunConfig.model_validate(values)


def _risk_config(*, active_kills: tuple[str, ...] = ()) -> BacktestRunConfig:
    inline = _inline_config()
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
        workspace_id=inline.workspace_id,
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
            workspace_id=None if scope is RiskScope.GLOBAL else inline.workspace_id,
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
    replay = ReferenceRiskReplay(
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
        active_kills=active_kills,
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
        risk_replay=replay,
    )
    return BacktestRunConfig.model_validate(values)


def _risk_bundle(
    adapter: NautilusBacktestAdapter, config: BacktestRunConfig
) -> ReproducibilityBundle:
    assert config.risk_replay is not None
    version = config.risk_replay.agent_version
    return adapter.bundle_for(
        config,
        spec_hash=version.spec_hash,
        prompt_hash=version.prompt_hash,
        feature_manifest_hash=HASH,
        model_profile="reason_balanced",
        resolved_model_identifier="deterministic-reference-no-model",
        container_image_digest="sha256:deadbeef",
        code_version="abc1234",
        created_at=END,
    )


@pytest.fixture
def adapter() -> NautilusBacktestAdapter:
    return NautilusBacktestAdapter()


@pytest.fixture
def bundle(adapter: NautilusBacktestAdapter) -> ReproducibilityBundle:
    return adapter.bundle_for(
        _config(),
        spec_hash=HASH,
        prompt_hash=HASH,
        feature_manifest_hash=HASH,
        model_profile="reason_balanced",
        resolved_model_identifier="mock-model-1",
        container_image_digest="sha256:deadbeef",
        code_version="abc1234",
    )


class TestEngineIdentity:
    def test_the_adapter_reports_the_real_engine_version(
        self, adapter: NautilusBacktestAdapter
    ) -> None:
        """ "The same backtest" on a different simulator is not the same backtest."""
        assert adapter.name == "nautilus_trader"
        assert adapter.version == nautilus_trader.__version__

    def test_the_pinned_version_matches_what_is_installed(self) -> None:
        """ADR 0012 pins a stable release; fill and fee semantics shift between versions."""
        assert nautilus_trader.__version__ == "1.231.0"


class TestEngineConstruction:
    def test_a_real_engine_is_built_with_our_models(self, adapter: NautilusBacktestAdapter) -> None:
        engine = adapter.build_engine(_config())
        try:
            assert engine is not None
            assert engine.trader_id.value == "KAVRIGO-001"
        finally:
            engine.dispose()

    def test_the_account_is_cash_not_margin(self, adapter: NautilusBacktestAdapter) -> None:
        """V1 is spot-only and non-custodial (ADR 0002). A margin account would let the
        simulation take leverage the product cannot."""
        import inspect

        source = inspect.getsource(adapter.build_engine)
        assert "AccountType.CASH" in source
        assert "AccountType.MARGIN" not in source


class TestPreflightRefusal:
    @pytest.mark.parametrize("instrument", ["BTC-USD.COINBASE", "BTC-USDT.SIM"])
    def test_risk_replay_requires_synthetic_usd_spot(self, instrument: str) -> None:
        config = _risk_config()
        assert config.risk_replay is not None
        version = config.risk_replay.agent_version
        spec = version.spec.model_copy(
            update={"universe": UniverseConfig(instruments=[InstrumentId.parse(instrument)])}
        )
        version = version.model_copy(update={"spec": spec, "spec_hash": content_hash(spec)})
        with pytest.raises(ValidationError, match="synthetic USD spot on SIM"):
            ReferenceRiskReplay.model_validate(
                config.risk_replay.model_dump(mode="python") | {"agent_version": version}
            )

    def test_a_clean_dataset_passes_preflight(self, adapter: NautilusBacktestAdapter) -> None:
        assert adapter.preflight(_config()) == []

    def test_inline_data_must_match_a_manifest_source_hash(self) -> None:
        config = _inline_config()
        source = config.dataset.sources[0].model_copy(update={"content_hash": HASH})
        values = config.model_dump(mode="python")
        values["dataset"] = config.dataset.model_copy(update={"sources": [source]})

        with pytest.raises(ValidationError, match="not bound to a matching manifest source"):
            BacktestRunConfig.model_validate(values)

    def test_a_leaky_dataset_is_refused_before_any_engine_work(
        self, adapter: NautilusBacktestAdapter, bundle: ReproducibilityBundle
    ) -> None:
        """Producing a number from a dataset that could see the future is worse than producing
        none, because the number is quotable."""
        config = _config(dataset=_manifest(time_basis=TimeBasis.EVENT_TIME))
        result = adapter.run(config, bundle=bundle)
        assert result.status is RunStatus.REFUSED
        assert result.metrics is None
        assert result.refusal_reason is not None
        assert any("not_point_in_time" in f for f in result.leakage_findings)
        assert not result.is_publishable

    def test_a_revised_dataset_is_refused(
        self, adapter: NautilusBacktestAdapter, bundle: ReproducibilityBundle
    ) -> None:
        source = _manifest().sources[0].model_copy(update={"contains_revisions": True})
        config = _config(dataset=_manifest(sources=[source]))
        assert adapter.run(config, bundle=bundle).status is RunStatus.REFUSED

    def test_risk_replay_rejects_bars_spanning_multiple_utc_days(self) -> None:
        config = _risk_config()
        assert config.inline_data is not None
        bars = list(config.inline_data.bars)
        bars[-1] = bars[-1].model_copy(
            update={
                "event_time": bars[-1].event_time + timedelta(days=1),
                "ingested_at": bars[-1].ingested_at + timedelta(days=1),
            }
        )
        inline_data = InlineBarDataset(bars=tuple(bars), content_hash=bar_dataset_hash(tuple(bars)))
        source = config.dataset.sources[0].model_copy(
            update={
                "content_hash": inline_data.content_hash,
                "last_event_time": bars[-1].event_time,
                "last_ingested_at": bars[-1].ingested_at,
            }
        )
        dataset = config.dataset.model_copy(
            update={
                "created_at": bars[-1].ingested_at,
                "period_end": bars[-1].ingested_at,
                "sources": [source],
            }
        )

        with pytest.raises(ValidationError, match="supports one UTC day"):
            BacktestRunConfig.model_validate(
                config.model_dump(mode="python") | {"dataset": dataset, "inline_data": inline_data}
            )

    def test_bar_replay_rejects_a_policy_requiring_book_freshness(self) -> None:
        config = _risk_config()
        assert config.risk_replay is not None
        policies = list(config.risk_replay.policies)
        policy = policies[0].model_copy(
            update={
                "freshness": FreshnessPolicy(
                    required_families=[DataFamily.CANDLES, DataFamily.BOOK],
                    max_age_ms={DataFamily.CANDLES: 5000, DataFamily.BOOK: 5000},
                )
            }
        )
        policies[0] = policy.model_copy(
            update={
                "content_hash": content_hash(
                    policy.model_dump(mode="python", exclude={"content_hash"})
                )
            }
        )

        with pytest.raises(ValidationError, match="candle freshness only"):
            ReferenceRiskReplay.model_validate(
                config.risk_replay.model_dump(mode="python") | {"policies": policies}
            )

    @pytest.mark.parametrize("unsupported_cost", ["minimum_fee", "adv_impact"])
    def test_risk_replay_rejects_cost_terms_the_gate_does_not_model(
        self, unsupported_cost: str
    ) -> None:
        config = _risk_config()
        if unsupported_cost == "minimum_fee":
            fees = config.costs.fees.model_copy(
                update={"minimum_fee": Money(amount=Decimal("0.01"), currency="USD")}
            )
            costs = config.costs.model_copy(update={"fees": fees})
        else:
            slippage = config.costs.slippage.model_copy(
                update={"impact_bps_per_unit_adv": Decimal("1")}
            )
            costs = config.costs.model_copy(update={"slippage": slippage})

        with pytest.raises(ValidationError, match="does not yet model minimum fees or ADV"):
            BacktestRunConfig.model_validate(config.model_dump(mode="python") | {"costs": costs})


class TestRun:
    def test_risk_replay_without_order_signals_completes_with_its_hash(
        self, adapter: NautilusBacktestAdapter
    ) -> None:
        config = _risk_config()
        assert config.inline_data is not None
        bars = tuple(
            bar.model_copy(
                update={
                    "open": Decimal(100),
                    "high": Decimal(100),
                    "low": Decimal(100),
                    "close": Decimal(100),
                }
            )
            for bar in config.inline_data.bars
        )
        data = InlineBarDataset(bars=bars, content_hash=bar_dataset_hash(bars))
        source = config.dataset.sources[0].model_copy(update={"content_hash": data.content_hash})
        config = BacktestRunConfig.model_validate(
            config.model_dump(mode="python")
            | {
                "inline_data": data,
                "dataset": config.dataset.model_copy(update={"sources": [source]}),
            }
        )

        result = adapter.run(config, bundle=_risk_bundle(adapter, config))

        assert result.status is RunStatus.COMPLETED
        assert result.risk_evaluations == result.risk_approvals == result.orders_submitted == 0
        assert result.risk_reason_counts == {}
        assert config.risk_replay is not None
        assert result.risk_replay_hash == config.risk_replay.replay_hash

    def test_a_clean_run_completes_and_reports_no_activity(
        self, adapter: NautilusBacktestAdapter, bundle: ReproducibilityBundle
    ) -> None:
        """No strategy is wired yet (that is step 10), so a run must report zero decisions
        rather than be dressed up as a result."""
        result = adapter.run(_config(), bundle=bundle)
        assert result.status is RunStatus.COMPLETED
        assert result.decisions_evaluated == 0
        assert result.orders_submitted == 0
        assert result.metrics is not None
        assert result.metrics.trade_count == 0
        assert result.metrics.net_return == 0

    def test_the_result_carries_the_cost_model_and_bundle(
        self, adapter: NautilusBacktestAdapter, bundle: ReproducibilityBundle
    ) -> None:
        """Spec 33: methodology travels with any shared figure."""
        result = adapter.run(_config(), bundle=bundle)
        assert result.cost_model.fees.taker_bps == Decimal("10")
        assert result.bundle.engine_name == "nautilus_trader"
        assert result.bundle.engine_version == "1.231.0"

    def test_an_inline_btc_fixture_executes_and_reports_after_cost_benchmark_metrics(
        self, adapter: NautilusBacktestAdapter
    ) -> None:
        config = _inline_config()
        bundle = adapter.bundle_for(
            config,
            spec_hash=HASH,
            prompt_hash=HASH,
            feature_manifest_hash=HASH,
            model_profile="reference_strategy",
            resolved_model_identifier="no-model",
            container_image_digest="sha256:deadbeef",
            code_version="fixture-v1",
            created_at=END,
        )

        result = adapter.run(config, bundle=bundle)

        assert result.status is RunStatus.COMPLETED
        assert result.decisions_evaluated == 53
        assert result.orders_submitted == 4
        assert result.orders_rejected_by_risk == 0
        assert result.metrics is not None
        assert result.metrics.trade_count == 2
        assert result.metrics.total_fees.amount > 0
        assert result.metrics.benchmark_return is not None
        assert result.metrics.net_return < result.metrics.gross_return
        assert result.limitations == sorted(result.limitations)
        assert not result.is_publishable

    def test_inline_execution_is_deterministic_for_one_frozen_config(
        self, adapter: NautilusBacktestAdapter
    ) -> None:
        config = _inline_config()
        bundle = adapter.bundle_for(
            config,
            spec_hash=HASH,
            prompt_hash=HASH,
            feature_manifest_hash=HASH,
            model_profile="reference_strategy",
            resolved_model_identifier="no-model",
            container_image_digest="sha256:deadbeef",
            code_version="fixture-v1",
            created_at=END,
        )

        first = adapter.run(config, bundle=bundle)
        second = adapter.run(config, bundle=bundle)

        assert first.metrics == second.metrics
        assert first.decisions_evaluated == second.decisions_evaluated
        assert first.orders_submitted == second.orders_submitted

    def test_a_hash_verified_parquet_catalog_executes_the_same_reference_path(
        self, tmp_path: Path
    ) -> None:
        config = _catalog_config(tmp_path)
        adapter = NautilusBacktestAdapter(catalog=LocalParquetBarCatalog(tmp_path))
        bundle = adapter.bundle_for(
            config,
            spec_hash=HASH,
            prompt_hash=HASH,
            feature_manifest_hash=HASH,
            model_profile="reference_strategy",
            resolved_model_identifier="no-model",
            container_image_digest="sha256:deadbeef",
            code_version="fixture-v1",
            created_at=END,
        )

        result = adapter.run(config, bundle=bundle)

        assert result.status is RunStatus.COMPLETED
        assert result.decisions_evaluated == 53
        assert result.orders_submitted == 4
        assert result.metrics is not None
        assert result.metrics.trade_count == 2
        assert "local_parquet_catalog_not_production_snapshot" in result.limitations
        assert "inline_fixture_not_catalog_dataset" not in result.limitations
        assert not result.is_publishable

    def test_a_catalog_run_refuses_when_the_worker_has_no_trusted_root(
        self, tmp_path: Path
    ) -> None:
        config = _catalog_config(tmp_path)
        adapter = NautilusBacktestAdapter()
        bundle = adapter.bundle_for(
            config,
            spec_hash=HASH,
            prompt_hash=HASH,
            feature_manifest_hash=HASH,
            model_profile="reference_strategy",
            resolved_model_identifier="no-model",
            container_image_digest="sha256:deadbeef",
            code_version="fixture-v1",
            created_at=END,
        )

        result = adapter.run(config, bundle=bundle)

        assert result.status is RunStatus.REFUSED
        assert result.leakage_findings == ["catalog_unconfigured"]

    def test_a_catalog_run_refuses_changed_bytes_without_exposing_the_path(
        self, tmp_path: Path
    ) -> None:
        config = _catalog_config(tmp_path)
        target = tmp_path / "fixtures" / "btc.parquet"
        target.write_bytes(target.read_bytes() + b"changed")
        adapter = NautilusBacktestAdapter(catalog=LocalParquetBarCatalog(tmp_path))
        bundle = adapter.bundle_for(
            config,
            spec_hash=HASH,
            prompt_hash=HASH,
            feature_manifest_hash=HASH,
            model_profile="reference_strategy",
            resolved_model_identifier="no-model",
            container_image_digest="sha256:deadbeef",
            code_version="fixture-v1",
            created_at=END,
        )

        result = adapter.run(config, bundle=bundle)

        assert result.status is RunStatus.REFUSED
        assert result.leakage_findings == ["catalog_integrity_invalid"]
        assert result.refusal_reason is not None
        assert str(tmp_path) not in result.refusal_reason

    def test_usd_reference_orders_pass_through_the_real_deterministic_risk_gate(
        self, adapter: NautilusBacktestAdapter
    ) -> None:
        config = _risk_config()

        result = adapter.run(config, bundle=_risk_bundle(adapter, config))

        assert result.status is RunStatus.COMPLETED
        assert result.risk_evaluations == 4
        assert result.risk_approvals == 4
        assert result.orders_rejected_by_risk == 0
        assert result.orders_submitted == 4
        assert config.risk_replay is not None
        assert result.risk_replay_hash == config.risk_replay.replay_hash
        assert "deterministic_risk_policy_not_replayed" not in result.limitations
        assert "reference_strategy_not_agent_runtime" in result.limitations
        assert result.risk_reason_counts["approved"] == 4
        assert not result.is_publishable

    def test_risk_rejection_never_reaches_nautilus_execution(
        self, adapter: NautilusBacktestAdapter
    ) -> None:
        config = _risk_config(active_kills=("global",))

        result = adapter.run(config, bundle=_risk_bundle(adapter, config))

        assert result.status is RunStatus.COMPLETED
        assert result.risk_evaluations > 0
        assert result.risk_approvals == 0
        assert result.orders_rejected_by_risk == result.risk_evaluations
        assert result.orders_submitted == 0
        assert result.risk_reason_counts["kill_switch_active"] == result.risk_evaluations

    def test_risk_evaluator_failure_never_reaches_nautilus_execution(
        self, adapter: NautilusBacktestAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _risk_config()

        def fail_evaluation(*_args: object, **_kwargs: object) -> None:
            raise ArithmeticError("synthetic evaluator failure")

        monkeypatch.setattr(
            "kavrigo_nautilus.risk_replay.LocalRiskSession.evaluate", fail_evaluation
        )

        result = adapter.run(config, bundle=_risk_bundle(adapter, config))

        assert result.status is RunStatus.COMPLETED
        assert result.risk_evaluations > 0
        assert result.risk_approvals == 0
        assert result.orders_rejected_by_risk == result.risk_evaluations
        assert result.orders_submitted == 0
        assert result.risk_reason_counts["unknown_account_state"] == result.risk_evaluations

    def test_risk_replay_refuses_a_bundle_from_another_configuration(
        self, adapter: NautilusBacktestAdapter
    ) -> None:
        config = _risk_config()
        bundle = _risk_bundle(adapter, config).model_copy(update={"config_hash": HASH})

        result = adapter.run(config, bundle=bundle)

        assert result.status is RunStatus.REFUSED
        assert result.leakage_findings == ["risk_replay_bundle_mismatch"]

    def test_two_runs_of_one_configuration_produce_the_same_bundle_hash(
        self, adapter: NautilusBacktestAdapter
    ) -> None:
        config = _config()
        created = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)
        kwargs = {
            "spec_hash": HASH,
            "prompt_hash": HASH,
            "feature_manifest_hash": HASH,
            "model_profile": "reason_balanced",
            "resolved_model_identifier": "mock-model-1",
            "container_image_digest": "sha256:deadbeef",
            "code_version": "abc1234",
            "created_at": created,
        }
        first = adapter.bundle_for(config, **kwargs)  # type: ignore[arg-type]
        second = adapter.bundle_for(config, **kwargs)  # type: ignore[arg-type]
        assert first.bundle_hash == second.bundle_hash

    def test_the_bundle_records_the_dataset_and_policies(
        self, adapter: NautilusBacktestAdapter, bundle: ReproducibilityBundle
    ) -> None:
        config = _config()
        assert bundle.dataset_manifest_hash == config.dataset.manifest_hash
        assert bundle.risk_policy_id == config.spec.risk_policy_ref
        assert bundle.execution_policy_id == config.spec.execution_policy_ref
        assert bundle.random_seed == 42
