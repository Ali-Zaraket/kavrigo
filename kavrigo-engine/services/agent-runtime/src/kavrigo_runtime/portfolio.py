"""Conservative deterministic allocation, never risk approval or execution (§6.5).

V1 uses configured overlap groups. It does not invent correlations or assume USD stablecoin
parity. Estimated sale proceeds never fund a competing buy before an actual fill.
"""

from decimal import ROUND_DOWN, Decimal, localcontext

from kavrigo_domain import AgentDecision, Money, PortfolioSnapshot, ProposedAction, content_hash
from kavrigo_domain.numeric import DECIMAL_CONTEXT
from kavrigo_runtime.contracts import Allocation, PortfolioDecision, RuntimePolicy

_QUANTUM = Decimal("0.000000000001")


def allocate(
    decisions: tuple[AgentDecision, ...], portfolio: PortfolioSnapshot, policy: RuntimePolicy
) -> PortfolioDecision:
    proposed = [decision for decision in decisions if decision.proposed_action.requires_order]
    with localcontext(DECIMAL_CONTEXT):
        return _allocate(proposed, portfolio, policy)


def _allocate(
    decisions: list[AgentDecision], portfolio: PortfolioSnapshot, policy: RuntimePolicy
) -> PortfolioDecision:
    reasons: list[str] = []
    if portfolio.base_currency != "USD":
        reasons.append("unsupported_valuation_currency")
    if not portfolio.is_reconciled or portfolio.reconciled_at is None:
        reasons.append("unknown_portfolio")
    if portfolio.open_order_count:
        reasons.append("pending_orders_require_reconciliation")
    if portfolio.equity.amount <= 0:
        reasons.append("nonpositive_equity")
    positions: dict[str, Decimal] = {}
    groups: dict[str, Decimal] = {}
    for position in portfolio.positions:
        value = position.market_value
        group = policy.allocation_groups.get(position.instrument_id.value)
        if (
            value is None
            or value.currency != "USD"
            or value.amount < 0
            or position.quantity.value < 0
            or group is None
        ):
            reasons.append("unknown_position_exposure")
            continue
        positions[position.instrument_id.value] = value.amount
        groups[group] = groups.get(group, Decimal(0)) + value.amount

    cash = max(Decimal(0), portfolio.available_cash.amount)
    remaining = max(Decimal(0), portfolio.equity.amount * policy.max_new_allocation_pct / 100)
    group_cap = max(Decimal(0), portfolio.equity.amount * policy.max_group_exposure_pct / 100)
    buffer_factor = 1 + policy.fee_buffer_bps / 10_000
    allocations: list[Allocation] = []
    # Ranking includes the model's estimated cost, but cannot authorize execution. Risk uses
    # trusted cost/market policy independently. Stable tie breaks make replay order invariant.
    ranked = sorted(
        decisions,
        key=lambda d: (
            -(Decimal(d.prediction.expected_return_bps) - (d.estimated_cost_bps or Decimal(0))),
            -Decimal(str(d.prediction.confidence)),
            d.instrument_id.value,
            d.decision_id,
        ),
    )
    for decision in ranked:
        requested = decision.proposed_notional
        assert requested is not None  # validated trade proposals always carry notional
        amount = Decimal(0)
        codes = list(dict.fromkeys(reasons))
        group = policy.allocation_groups.get(decision.instrument_id.value)
        if requested.currency != "USD" or decision.instrument_id.quote != "USD":
            codes.append("unsupported_valuation_currency")
        if group is None:
            codes.append("unknown_overlap_group")
        if not codes:
            assert group is not None
            if decision.proposed_action is ProposedAction.BUY:
                amount = max(
                    Decimal(0),
                    min(
                        requested.amount,
                        cash / buffer_factor,
                        remaining,
                        group_cap - groups.get(group, Decimal(0)),
                    ),
                ).quantize(_QUANTUM, rounding=ROUND_DOWN)
                cash -= amount * buffer_factor
                remaining -= amount
                groups[group] = groups.get(group, Decimal(0)) + amount
            else:
                held = positions.get(decision.instrument_id.value, Decimal(0))
                amount = min(requested.amount, held).quantize(_QUANTUM, rounding=ROUND_DOWN)
                positions[decision.instrument_id.value] = held - amount
            codes.append(
                "allocated"
                if amount == requested.amount
                else "allocation_reduced"
                if amount > 0
                else "allocation_unavailable"
            )
        allocations.append(
            Allocation(
                decision_id=decision.decision_id,
                instrument_id=decision.instrument_id,
                requested_notional=requested,
                allocated_notional=Money(amount=amount, currency=requested.currency),
                reason_codes=tuple(codes),
            )
        )
    return PortfolioDecision(
        portfolio_hash=content_hash(portfolio),
        allocations=tuple(allocations),
        reason_codes=tuple(dict.fromkeys(reasons)),
    )
