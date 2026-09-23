"""The Nautilus adapter against a real NautilusTrader engine.

These construct an actual ``BacktestEngine`` rather than a mock: the point of ADR 0012 was to
get a real simulator's fill semantics, and a test that never touches it would not notice a
version whose API had moved underneath us.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import nautilus_trader
import pytest
from pydantic import ValidationError

from kavrigo_backtest import (
    BacktestBar,
    BacktestRunConfig,
    CostModel,
    DatasetManifest,
    DatasetSource,
    FeeSchedule,
    InlineBarDataset,
    LatencyModel,
    LongOnlyEmaStrategy,
    ReproducibilityBundle,
    RunStatus,
    SlippageModel,
    TimeBasis,
    bar_dataset_hash,
)
from kavrigo_domain import (
    AgentSpec,
    DataPack,
    InstrumentId,
    ModelPolicy,
    Money,
    ScheduleConfig,
    UniverseConfig,
)
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


class TestRun:
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
