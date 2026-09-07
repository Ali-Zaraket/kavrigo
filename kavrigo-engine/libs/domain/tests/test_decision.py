"""The decision contract: a model output is a proposal, never an order."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from kavrigo_domain import (
    AgentDecision,
    DecisionState,
    InstrumentId,
    MarketRegime,
    Money,
    Prediction,
    ProposedAction,
    SignalScores,
)
from kavrigo_domain.testing import AS_OF, oid


def _decision(**overrides: object) -> AgentDecision:
    base: dict[str, object] = {
        "decision_id": oid("dec"),
        "workspace_id": oid("ws"),
        "agent_version_id": oid("av"),
        "snapshot_id": oid("snap"),
        "instrument_id": InstrumentId.parse("BTC-USDT.BINANCE"),
        "decided_at": AS_OF,
        "market_regime": MarketRegime.RANGE,
        "state": DecisionState.NEUTRAL,
        "signals": SignalScores(),
        "prediction": Prediction(
            expected_return_bps=18, confidence=0.6, uncertainty=0.3, horizon_minutes=60
        ),
        "proposed_action": ProposedAction.NO_TRADE,
    }
    return AgentDecision(**{**base, **overrides})  # type: ignore[arg-type]


class TestAbstention:
    """``AGENTS.md`` domain rule 4: NO_TRADE and UNKNOWN are successful outcomes."""

    def test_no_trade_is_a_valid_decision(self) -> None:
        decision = _decision()
        assert decision.is_abstention
        assert decision.proposed_notional is None

    def test_unknown_state_cannot_propose_a_trade(self) -> None:
        with pytest.raises(ValidationError, match="UNKNOWN state cannot propose a trade"):
            _decision(
                state=DecisionState.UNKNOWN,
                proposed_action=ProposedAction.BUY,
                proposed_notional=Money(amount="100", currency="USDT"),
            )

    def test_no_trade_must_not_carry_a_notional(self) -> None:
        with pytest.raises(ValidationError, match="must not carry a non-zero notional"):
            _decision(proposed_notional=Money(amount="100", currency="USDT"))


class TestOrderProposals:
    def test_buy_requires_a_notional(self) -> None:
        with pytest.raises(ValidationError, match="requires a non-zero proposed notional"):
            _decision(state=DecisionState.BULLISH, proposed_action=ProposedAction.BUY)

    def test_notional_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="notional must be positive"):
            _decision(
                state=DecisionState.BEARISH,
                proposed_action=ProposedAction.SELL,
                proposed_notional=Money(amount="-100", currency="USDT"),
            )

    def test_a_valid_buy_proposal(self) -> None:
        decision = _decision(
            state=DecisionState.BULLISH,
            proposed_action=ProposedAction.BUY,
            proposed_notional=Money(amount="500", currency="USDT"),
            estimated_cost_bps=Decimal("8"),
        )
        assert not decision.is_abstention
        assert decision.proposed_notional is not None


class TestEvidence:
    def test_evidence_cannot_both_support_and_contradict(self) -> None:
        shared = oid("ev")
        with pytest.raises(ValidationError, match="both supporting and contradicting"):
            _decision(evidence_refs=[shared], contradicting_evidence_refs=[shared])


class TestPrediction:
    def test_confidence_and_uncertainty_cannot_jointly_exceed_one(self) -> None:
        with pytest.raises(ValidationError, match="cannot jointly exceed"):
            Prediction(expected_return_bps=10, confidence=0.9, uncertainty=0.5, horizon_minutes=60)

    def test_signal_scores_are_bounded(self) -> None:
        with pytest.raises(ValidationError):
            SignalScores(price=1.5)


def test_proposed_action_closed_set_covers_only_trading_verbs() -> None:
    """There is no representation for withdraw, transfer, or a free-form instruction."""
    assert {a.value for a in ProposedAction} == {
        "buy",
        "sell",
        "reduce",
        "close",
        "hold",
        "no_trade",
    }
