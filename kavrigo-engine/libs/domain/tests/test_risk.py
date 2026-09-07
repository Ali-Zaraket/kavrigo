"""Risk evaluation invariants (ADR 0004).

These tests exist to make one property unfalsifiable at the type level: a risk evaluation can
only ever *reduce* what was requested, and a rejection approves nothing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from kavrigo_domain import (
    DataFamily,
    EventRiskPolicy,
    FreshnessPolicy,
    Money,
    RiskDecision,
    RiskEvaluation,
    RiskLimits,
    RiskPolicy,
    RiskReasonCode,
    RiskScope,
)
from kavrigo_domain.testing import AS_OF, HASH, oid


def _limits(**overrides: object) -> RiskLimits:
    base: dict[str, object] = {
        "max_gross_exposure_pct": Decimal("50"),
        "max_single_asset_exposure_pct": Decimal("15"),
        "max_network_exposure_pct": Decimal("25"),
        "max_open_positions": 6,
        "max_daily_loss_pct": Decimal("2"),
        "max_drawdown_pct": Decimal("8"),
        "min_liquidity_usd": Decimal("5000000"),
        "max_spread_bps": 20,
        "min_order_notional_usd": Decimal("10"),
        "max_order_notional_usd": Decimal("10000"),
    }
    return RiskLimits(**{**base, **overrides})  # type: ignore[arg-type]


def _evaluation(**overrides: object) -> RiskEvaluation:
    base: dict[str, object] = {
        "risk_evaluation_id": oid("re"),
        "order_intent_id": oid("oi"),
        "decision_id": oid("dec"),
        "workspace_id": oid("ws"),
        "evaluated_at": AS_OF,
        "decision": RiskDecision.APPROVED,
        "reason_codes": [RiskReasonCode.APPROVED],
        "applied_policy_ids": [oid("rp")],
        "requested_notional": Money(amount="1000", currency="USDT"),
        "approved_notional": Money(amount="1000", currency="USDT"),
        "evaluator_version": "v1",
    }
    return RiskEvaluation(**{**base, **overrides})  # type: ignore[arg-type]


class TestRiskCanOnlyReduce:
    def test_approving_more_than_requested_is_impossible(self) -> None:
        with pytest.raises(ValidationError, match="never approve more than was requested"):
            _evaluation(approved_notional=Money(amount="1001", currency="USDT"))

    def test_resized_must_be_strictly_smaller(self) -> None:
        with pytest.raises(ValidationError, match="strictly smaller"):
            _evaluation(decision=RiskDecision.APPROVED_RESIZED)

    def test_approved_must_be_the_full_amount(self) -> None:
        with pytest.raises(ValidationError, match="requires the full requested notional"):
            _evaluation(approved_notional=Money(amount="500", currency="USDT"))

    def test_a_valid_resize(self) -> None:
        evaluation = _evaluation(
            decision=RiskDecision.APPROVED_RESIZED,
            reason_codes=[
                RiskReasonCode.APPROVED_RESIZED,
                RiskReasonCode.MAX_POSITION_EXCEEDED,
            ],
            approved_notional=Money(amount="400", currency="USDT"),
            binding_scope=RiskScope.ASSET,
        )
        assert evaluation.is_approved
        assert evaluation.approved_notional.amount < evaluation.requested_notional.amount


class TestRejection:
    def test_rejection_must_approve_zero(self) -> None:
        with pytest.raises(ValidationError, match="must approve zero notional"):
            _evaluation(
                decision=RiskDecision.REJECTED,
                reason_codes=[RiskReasonCode.STALE_DATA],
            )

    def test_rejection_cannot_claim_approval(self) -> None:
        with pytest.raises(ValidationError, match="cannot carry the APPROVED reason code"):
            _evaluation(
                decision=RiskDecision.REJECTED,
                reason_codes=[RiskReasonCode.APPROVED],
                approved_notional=Money(amount="0", currency="USDT"),
            )

    def test_a_valid_rejection_is_explainable(self) -> None:
        evaluation = _evaluation(
            decision=RiskDecision.REJECTED,
            reason_codes=[RiskReasonCode.STALE_DATA, RiskReasonCode.DATA_QUALITY_BELOW_MINIMUM],
            approved_notional=Money(amount="0", currency="USDT"),
        )
        assert not evaluation.is_approved
        assert evaluation.reason_codes  # machine-readable, never free text alone

    def test_reason_codes_are_mandatory(self) -> None:
        with pytest.raises(ValidationError):
            _evaluation(reason_codes=[])

    def test_currency_must_match(self) -> None:
        with pytest.raises(ValidationError, match="share a currency"):
            _evaluation(approved_notional=Money(amount="1000", currency="USD"))


class TestRiskLimits:
    def test_single_asset_limit_cannot_exceed_gross_limit(self) -> None:
        with pytest.raises(ValidationError, match="exceeds the gross exposure limit"):
            _limits(max_single_asset_exposure_pct=Decimal("80"))

    def test_order_notional_bounds_must_be_ordered(self) -> None:
        with pytest.raises(ValidationError, match="exceeds max_order_notional_usd"):
            _limits(min_order_notional_usd=Decimal("50000"))

    def test_percentages_are_bounded(self) -> None:
        with pytest.raises(ValidationError):
            _limits(max_gross_exposure_pct=Decimal("150"))

    def test_limits_reject_float_input(self) -> None:
        with pytest.raises(ValidationError, match="binary float"):
            _limits(min_liquidity_usd=5_000_000.0)


class TestPolicy:
    def test_policy_is_versioned_and_hashed(self) -> None:
        policy = RiskPolicy(
            risk_policy_id=oid("rp"),
            workspace_id=oid("ws"),
            version=17,
            scope=RiskScope.WORKSPACE,
            limits=_limits(),
            freshness=FreshnessPolicy(
                max_age_ms={
                    DataFamily.TRADES: 5_000,
                    DataFamily.BOOK: 2_000,
                    DataFamily.DERIVATIVES: 120_000,
                    DataFamily.NEWS: 900_000,
                },
                required_families=[DataFamily.TRADES, DataFamily.BOOK],
            ),
            event_risk=EventRiskPolicy(block_new_positions_before_macro_minutes=10),
            created_at=AS_OF,
            created_by="user_1",
            content_hash=HASH,
        )
        assert policy.freshness.limit_for(DataFamily.TRADES) == 5_000
        assert policy.freshness.limit_for(DataFamily.ONCHAIN) is None

    def test_policies_are_immutable(self) -> None:
        limits = _limits()
        with pytest.raises(ValidationError):
            limits.max_open_positions = 100  # type: ignore[misc]


def test_every_reason_code_is_unique_and_snake_case() -> None:
    values = [code.value for code in RiskReasonCode]
    assert len(values) == len(set(values))
    assert all(value.islower() and " " not in value for value in values)
