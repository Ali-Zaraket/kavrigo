from datetime import UTC, datetime
from decimal import Decimal, localcontext

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kavrigo_domain import AgentDecision, Money, Position, Price, ProposedAction, Quantity
from kavrigo_runtime.portfolio import allocate

from .conftest import AV, BTC, ETH, WS


def decision(proposal, instrument=BTC, suffix="1"):
    return AgentDecision.model_validate(
        {
            **proposal.model_dump(mode="python"),
            "decision_id": "dec_" + suffix * 32,
            "workspace_id": WS,
            "agent_version_id": AV,
            "snapshot_id": "snap_" + "7" * 32,
            "instrument_id": instrument,
            "decided_at": datetime(2026, 9, 8, 12, tzinfo=UTC),
        }
    )


def money(value):
    return Money(amount=Decimal(value), currency="USD")


def test_competing_allocations_do_not_spend_reserved_cash(proposal, portfolio, policy):
    portfolio = portfolio.model_copy(update={"reserved_cash": money("900")})
    decisions = (decision(proposal, BTC, "1"), decision(proposal, ETH, "2"))
    result = allocate(decisions, portfolio, policy)
    cost = sum(a.allocated_notional.amount for a in result.allocations) * Decimal("1.001")
    assert cost <= Decimal("100")
    assert result.allocations[1].allocated_notional.is_zero
    assert allocate(tuple(reversed(decisions)), portfolio, policy) == result


def test_sale_cannot_fund_competing_buy_before_fill(proposal, portfolio, policy):
    position = Position(
        instrument_id=BTC,
        quantity=Quantity(value="1", asset="BTC"),
        mark_price=Price(value="300", base="BTC", quote="USD"),
        realized_pnl=money("0"),
        unrealized_pnl=money("0"),
        network="crypto",
    )
    portfolio = portfolio.model_copy(
        update={
            "positions": [position],
            "cash": money("0"),
            "equity": money("300"),
            "gross_exposure": money("300"),
            "net_exposure": money("300"),
        }
    )
    sell = decision(proposal.model_copy(update={"proposed_action": ProposedAction.SELL}), BTC, "1")
    buy = decision(proposal, ETH, "2")
    result = allocate((sell, buy), portfolio, policy)
    assert result.allocations[0].allocated_notional.amount == Decimal("300")
    assert result.allocations[1].allocated_notional.is_zero


@pytest.mark.parametrize("unknown", ["group", "mark", "orders", "reconciliation"])
def test_unknown_portfolio_state_refuses_allocation(proposal, portfolio, policy, unknown):
    if unknown == "group":
        policy = policy.model_copy(update={"allocation_groups": {}})
    elif unknown == "mark":
        position = Position(
            instrument_id=BTC,
            quantity=Quantity(value="1", asset="BTC"),
            realized_pnl=money("0"),
            unrealized_pnl=money("0"),
        )
        portfolio = portfolio.model_copy(update={"positions": [position]})
    elif unknown == "orders":
        portfolio = portfolio.model_copy(update={"open_order_count": 1})
    else:
        portfolio = portfolio.model_copy(update={"is_reconciled": False})
    result = allocate((decision(proposal),), portfolio, policy)
    assert result.allocations[0].allocated_notional.is_zero


def test_allocation_independent_of_caller_decimal_context(proposal, portfolio, policy):
    decisions = (decision(proposal), decision(proposal, ETH, "2"))
    expected = allocate(decisions, portfolio, policy)
    with localcontext() as context:
        context.prec = 3
        assert allocate(decisions, portfolio, policy) == expected


@given(st.lists(st.integers(min_value=1, max_value=10000), min_size=1, max_size=16))
def test_total_allocation_cannot_exceed_cash_group_or_budget(amounts):
    # Construct fixtures explicitly; this property is independent of pytest fixture mutation.
    from kavrigo_domain import DecisionProposal, PortfolioSnapshot, TradingMode
    from kavrigo_runtime import RuntimePolicy, ScannerPolicy

    now = datetime(2026, 9, 8, 12, tzinfo=UTC)
    portfolio = PortfolioSnapshot(
        workspace_id=WS,
        mode=TradingMode.PAPER,
        as_of=now,
        base_currency="USD",
        cash=money("1000"),
        reserved_cash=money("50"),
        realized_pnl_today=money("0"),
        unrealized_pnl=money("0"),
        equity=money("1000"),
        gross_exposure=money("0"),
        net_exposure=money("0"),
        peak_equity=money("1000"),
        reconciled_at=now,
    )
    policy = RuntimePolicy(
        version="fixture",
        code_version="fixture",
        code_image_digest="sha256:" + "0" * 64,
        scanner=ScannerPolicy(
            absolute_thresholds={"return_5m": Decimal("1")},
            candidate_ttl_ms=1000,
            max_candidates=16,
        ),
        max_snapshot_age_ms=1000,
        max_portfolio_age_ms=1000,
        max_calls_per_cycle=16,
        allocation_groups={BTC.value: "crypto"},
        max_new_allocation_pct=Decimal("50"),
        max_group_exposure_pct=Decimal("40"),
        fee_buffer_bps=Decimal("10"),
    )
    proposals = tuple(
        decision(
            DecisionProposal.model_validate(
                {
                    "market_regime": "trend_up",
                    "state": "bullish",
                    "signals": {},
                    "prediction": {
                        "expected_return_bps": 100,
                        "confidence": 0.5,
                        "uncertainty": 0.5,
                        "horizon_minutes": 60,
                    },
                    "proposed_action": "buy",
                    "proposed_notional": {"amount": str(amount), "currency": "USD"},
                }
            ),
            suffix=format(i, "x"),
        )
        for i, amount in enumerate(amounts)
    )
    result = allocate(proposals, portfolio, policy)
    total = sum(a.allocated_notional.amount for a in result.allocations)
    assert total <= Decimal("400")
    assert total * Decimal("1.001") <= portfolio.available_cash.amount
    assert all(
        0 <= a.allocated_notional.amount <= a.requested_notional.amount for a in result.allocations
    )
