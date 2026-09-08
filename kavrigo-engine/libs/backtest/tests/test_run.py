"""Run configuration, refusal semantics and the reproducibility bundle."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kavrigo_backtest import (
    BacktestResult,
    BacktestRunConfig,
    ReproducibilityBundle,
    RunStatus,
    refuse,
)
from kavrigo_domain import (
    AgentSpec,
    DataPack,
    InstrumentId,
    ModelCallRecord,
    ModelPolicy,
    Money,
    ScheduleConfig,
    UniverseConfig,
)

from .conftest import END, HASH, START, cost_model, manifest, oid

NOW = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)


def _spec(*instruments: str) -> AgentSpec:
    return AgentSpec(
        name="btc-baseline",
        universe=UniverseConfig(
            instruments=[InstrumentId.parse(i) for i in instruments or ("BTC-USDT.BINANCE",)]
        ),
        schedule=ScheduleConfig(decision_interval_seconds=900),
        data_packs=[DataPack.MARKET_MICROSTRUCTURE],
        model_policy=ModelPolicy(max_cost_per_decision_usd=Decimal("0.10")),
        risk_policy_ref=oid("rp"),
        execution_policy_ref=oid("ep"),
    )


def _config(**overrides: object) -> BacktestRunConfig:
    values: dict[str, object] = {
        "run_id": oid("run"),
        "workspace_id": oid("ws"),
        "agent_version_id": oid("av"),
        "spec": _spec(),
        "dataset": manifest(),
        "costs": cost_model(),
        "starting_balance": Money(amount=Decimal("10000"), currency="USDT"),
        "random_seed": 42,
    }
    values.update(overrides)
    return BacktestRunConfig(**values)  # type: ignore[arg-type]


def _bundle(**overrides: object) -> ReproducibilityBundle:
    values: dict[str, object] = {
        "run_id": oid("run"),
        "created_at": NOW,
        "dataset_manifest_hash": HASH,
        "config_hash": HASH,
        "agent_version_id": oid("av"),
        "spec_hash": HASH,
        "prompt_hash": HASH,
        "model_profile": "reason_balanced",
        "resolved_model_identifier": "mock-model-1",
        "feature_set_version": "v1",
        "feature_manifest_hash": HASH,
        "risk_policy_id": oid("rp"),
        "execution_policy_id": oid("ep"),
        "cost_model_hash": HASH,
        "random_seed": 42,
        "engine_name": "nautilus_trader",
        "engine_version": "1.231.0",
        "container_image_digest": "sha256:deadbeef",
        "code_version": "abc1234",
    }
    values.update(overrides)
    return ReproducibilityBundle(**values)  # type: ignore[arg-type]


class TestRunConfig:
    def test_the_dataset_must_cover_the_agents_universe(self) -> None:
        """Running an agent against data missing one of its instruments produces a result about
        a different agent."""
        with pytest.raises(ValidationError, match="does not cover every instrument"):
            _config(spec=_spec("SOL-USDT.BINANCE"))

    def test_a_non_positive_balance_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="starting balance must be positive"):
            _config(starting_balance=Money(amount=Decimal("0"), currency="USDT"))

    def test_the_config_hash_covers_the_seed(self) -> None:
        """Two runs claiming one configuration must not differ in their randomness."""
        assert _config(random_seed=1).config_hash != _config(random_seed=2).config_hash

    def test_the_config_hash_covers_the_cost_model(self) -> None:
        from kavrigo_backtest import LatencyModel

        cheap = cost_model(latency=LatencyModel(decision_to_venue_ms=0))
        assert _config(costs=cheap).config_hash != _config().config_hash

    def test_the_config_hash_is_stable(self) -> None:
        assert _config().config_hash == _config().config_hash


class TestReproducibilityBundle:
    def test_it_records_the_resolved_model_not_just_the_profile(self) -> None:
        """A routing fallback must never silently change what produced a result (ADR 0010)."""
        assert _bundle().resolved_model_identifier == "mock-model-1"

    def test_the_container_digest_is_mandatory(self) -> None:
        """A run whose code version is unknown cannot be reproduced however carefully its data
        was recorded."""
        with pytest.raises(ValidationError):
            _bundle(container_image_digest="")

    def test_the_bundle_hash_identifies_the_whole_combination(self) -> None:
        assert _bundle().bundle_hash != _bundle(code_version="def5678").bundle_hash

    def test_the_bundle_hash_is_stable(self) -> None:
        assert _bundle().bundle_hash == _bundle().bundle_hash

    def test_actual_model_calls_set_bundle_identity(self) -> None:
        bundle = _bundle()
        call = ModelCallRecord(
            model_call_id=oid("mc"),
            profile="reason_deep",
            resolved_model_identifier="mock-pinned-v2",
            prompt_hash="sha256:" + "cd" * 32,
            input_tokens=2,
            output_tokens=3,
            cost=Money(amount=Decimal("0.01"), currency="USD"),
            latency_ms=4,
            workspace_id=oid("ws"),
            agent_id=oid("ag"),
            agent_version_id=bundle.agent_version_id,
            decision_id=oid("dec"),
            request_hash=HASH,
            route_hash=HASH,
        )
        bound = bundle.with_model_calls((call,))
        assert bound.resolved_model_identifier == call.resolved_model_identifier
        assert bound.prompt_hash == call.prompt_hash
        assert bound.model_calls == (call,)
        assert bound.bundle_hash != bundle.bundle_hash
        with pytest.raises(ValueError, match="agent version"):
            bundle.with_model_calls((call.model_copy(update={"agent_version_id": oid("av", 9)}),))
        with pytest.raises(ValueError, match="successful"):
            bundle.with_model_calls(())


class TestRefusal:
    def test_a_refused_run_carries_no_metrics(self) -> None:
        """A leaky dataset must not produce a number somebody could quote."""
        result = refuse(
            _config(),
            reason="dataset is not point-in-time safe",
            started_at=NOW,
            bundle=_bundle(),
            findings=["not_point_in_time: cut on event_time"],
        )
        assert result.status is RunStatus.REFUSED
        assert result.metrics is None
        assert result.leakage_findings
        assert not result.is_publishable

    def test_a_refusal_must_state_a_reason(self) -> None:
        with pytest.raises(ValidationError, match="must say why"):
            BacktestResult(
                run_id=oid("run"),
                workspace_id=oid("ws"),
                status=RunStatus.REFUSED,
                started_at=NOW,
                period_start=START,
                period_end=END,
                cost_model=cost_model(),
                bundle=_bundle(),
            )

    def test_a_completed_run_must_carry_metrics(self) -> None:
        with pytest.raises(ValidationError, match="must carry metrics"):
            BacktestResult(
                run_id=oid("run"),
                workspace_id=oid("ws"),
                status=RunStatus.COMPLETED,
                started_at=NOW,
                period_start=START,
                period_end=END,
                cost_model=cost_model(),
                bundle=_bundle(),
            )

    def test_refused_is_distinct_from_failed(self) -> None:
        """A refusal is a judgement, not a crash, and must never read as either a crash or a
        result."""
        assert RunStatus.REFUSED != RunStatus.FAILED
        assert RunStatus.REFUSED != RunStatus.COMPLETED


class TestPublishability:
    def _completed(self, **overrides: object) -> BacktestResult:
        from kavrigo_backtest import EquityPoint, compute_metrics

        curve = [
            EquityPoint(
                at=START,
                equity=Money(amount=Decimal("10000"), currency="USDT"),
                exposure=Money.zero("USDT"),
            ),
            EquityPoint(
                at=END,
                equity=Money(amount=Decimal("11000"), currency="USDT"),
                exposure=Money.zero("USDT"),
            ),
        ]
        values: dict[str, object] = {
            "run_id": oid("run"),
            "workspace_id": oid("ws"),
            "status": RunStatus.COMPLETED,
            "started_at": NOW,
            "finished_at": NOW,
            "period_start": START,
            "period_end": END,
            "metrics": compute_metrics(curve=curve, trades=[], total_fees=Money.zero("USDT")),
            "cost_model": cost_model(),
            "bundle": _bundle(),
        }
        values.update(overrides)
        return BacktestResult(**values)  # type: ignore[arg-type]

    def test_a_clean_completed_run_is_publishable(self) -> None:
        assert self._completed().is_publishable

    def test_leakage_findings_block_publication(self) -> None:
        """A figure from a dataset that could see the future is worse than no figure."""
        assert not self._completed(leakage_findings=["contains_provider_revisions"]).is_publishable

    def test_optimism_warnings_travel_with_the_result(self) -> None:
        """Spec 33: methodology travels with any shared figure."""
        from kavrigo_backtest import LatencyModel

        optimistic = cost_model(latency=LatencyModel(decision_to_venue_ms=0))
        result = self._completed(
            cost_model=optimistic, optimism_warnings=optimistic.optimism_warnings
        )
        assert result.optimism_warnings
        # Still publishable — it is a disclosed assumption, not a leak.
        assert result.is_publishable
