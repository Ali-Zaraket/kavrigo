"""AgentSpec: the safety properties encoded in the spec itself."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kavrigo_domain import (
    AgentSpec,
    AgentVersion,
    AnalysisConfig,
    ApprovalStatus,
    DataPack,
    InstrumentId,
    ModelPolicy,
    ScheduleConfig,
    TradingMode,
    UniverseConfig,
    content_hash,
)
from kavrigo_domain.testing import AS_OF, HASH, oid


class TestLiveGate:
    """ADR 0001: a spec cannot be constructed in live mode during the paper-only phase."""

    def test_live_mode_is_refused(self, agent_spec: AgentSpec) -> None:
        with pytest.raises(ValidationError, match="live mode cannot be set"):
            agent_spec.model_copy(update={"mode": TradingMode.LIVE}).model_validate(
                {**agent_spec.model_dump(), "mode": "live"}
            )

    def test_default_mode_is_paper(self, agent_spec: AgentSpec) -> None:
        assert agent_spec.mode is TradingMode.PAPER


class TestUniverse:
    def test_non_spot_instruments_are_refused(self) -> None:
        perp = InstrumentId.parse("BTC-USDT.BINANCE:perpetual")
        with pytest.raises(ValidationError, match="not a spot instrument"):
            UniverseConfig(instruments=[perp])

    def test_universe_cannot_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            UniverseConfig(instruments=[])


class TestAnalysisConfig:
    def test_abstention_cannot_be_disabled(self) -> None:
        """``AGENTS.md`` domain rule 15: never encode always-trade behaviour."""
        with pytest.raises(ValidationError, match="abstention cannot be disabled"):
            AnalysisConfig(allow_abstain=False)

    def test_portfolio_layer_is_mandatory(self) -> None:
        with pytest.raises(ValidationError, match="portfolio layer is mandatory"):
            AnalysisConfig(portfolio_layer=False)


class TestSchedule:
    def test_sub_minute_intervals_are_refused(self) -> None:
        """V1 is explicitly not a high-frequency platform (spec §1.3)."""
        with pytest.raises(ValidationError):
            ScheduleConfig(decision_interval_seconds=5)

    def test_daily_decision_cap_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            ScheduleConfig(decision_interval_seconds=900, max_decisions_per_day=100_000)


class TestModelPolicy:
    def test_cost_cap_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="must be positive"):
            ModelPolicy(max_cost_per_decision_usd=Decimal("0"))

    def test_cost_cap_rejects_floats(self) -> None:
        with pytest.raises(ValidationError, match="binary float"):
            ModelPolicy(max_cost_per_decision_usd=0.1)  # type: ignore[arg-type]


class TestEvidenceRequirements:
    def test_news_requires_point_in_time_timestamps(self, btc: InstrumentId) -> None:
        from kavrigo_domain import EvidenceRequirements

        with pytest.raises(ValidationError, match="point-in-time timestamps"):
            AgentSpec(
                name="news-agent",
                universe=UniverseConfig(instruments=[btc]),
                schedule=ScheduleConfig(decision_interval_seconds=900),
                data_packs=[DataPack.NEWS],
                model_policy=ModelPolicy(max_cost_per_decision_usd=Decimal("0.10")),
                evidence=EvidenceRequirements(require_timestamps=False),
                risk_policy_ref=oid("rp"),
                execution_policy_ref=oid("ep"),
            )


class TestAgentVersion:
    def _version(self, spec: AgentSpec, **overrides: object) -> AgentVersion:
        base = {
            "agent_version_id": oid("av"),
            "agent_id": oid("ag"),
            "workspace_id": oid("ws"),
            "version": 1,
            "spec": spec,
            "spec_hash": content_hash(spec),
            "prompt_version_id": oid("pv"),
            "prompt_hash": HASH,
            "feature_set_version": "v1",
            "created_at": AS_OF,
            "created_by": "user_1",
        }
        return AgentVersion(**{**base, **overrides})  # type: ignore[arg-type]

    def test_versions_are_immutable(self, agent_spec: AgentSpec) -> None:
        version = self._version(agent_spec)
        with pytest.raises(ValidationError):
            version.version = 2  # type: ignore[misc]

    def test_unapproved_version_is_not_runnable(self, agent_spec: AgentSpec) -> None:
        assert not self._version(agent_spec).is_approved_for("paper-prod")

    def test_approval_is_per_environment(self, agent_spec: AgentSpec) -> None:
        version = self._version(
            agent_spec,
            approval_status=ApprovalStatus.APPROVED,
            approved_environments=["dev"],
        )
        assert version.is_approved_for("dev")
        assert not version.is_approved_for("paper-prod")

    def test_spec_hash_is_stable_for_equal_specs(self, agent_spec: AgentSpec) -> None:
        reparsed = AgentSpec.model_validate(agent_spec.model_dump())
        assert content_hash(agent_spec) == content_hash(reparsed)

    def test_spec_hash_changes_when_the_spec_changes(self, agent_spec: AgentSpec) -> None:
        changed = agent_spec.model_copy(
            update={"schedule": ScheduleConfig(decision_interval_seconds=3600)}
        )
        assert content_hash(agent_spec) != content_hash(changed)


def test_decision_interval_upper_bound_is_a_day() -> None:
    assert ScheduleConfig(decision_interval_seconds=86_400).decision_interval_seconds == int(
        timedelta(days=1).total_seconds()
    )
