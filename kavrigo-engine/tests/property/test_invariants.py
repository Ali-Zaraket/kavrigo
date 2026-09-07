"""Property-based invariants (``MASTER_BUILD_SPEC.md`` §37, ``AGENTS.md`` § step 11).

Example-based tests show that a rule holds for the cases someone thought of. These assert that it
holds for every value Hypothesis can construct. The invariants here are the ones whose failure
would move real money:

* risk can only reduce a requested notional, never enlarge it;
* a rejected evaluation approves nothing;
* money arithmetic is exact and unit-safe;
* instrument identity round-trips without ambiguity.

The risk *evaluator* does not exist yet; these prove the properties hold at the contract level,
so that when the evaluator is written it cannot express a violating result.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from kavrigo_domain import (
    InstrumentClass,
    InstrumentId,
    Money,
    Price,
    Quantity,
    RiskDecision,
    RiskEvaluation,
    RiskReasonCode,
    content_hash,
)

pytestmark = pytest.mark.property

AS_OF = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

# Bounded exact decimals: money, not scientific notation.
amounts = st.decimals(
    min_value=Decimal("0.00000001"),
    max_value=Decimal("100000000"),
    allow_nan=False,
    allow_infinity=False,
    places=8,
)
signed_amounts = st.decimals(
    min_value=Decimal("-100000000"),
    max_value=Decimal("100000000"),
    allow_nan=False,
    allow_infinity=False,
    places=8,
)
assets = st.sampled_from(["BTC", "ETH", "SOL", "USDT", "USD", "EUR"])
venues = st.sampled_from(["BINANCE", "COINBASE", "KRAKEN", "SIM"])


def _oid(prefix: str) -> str:
    return f"{prefix}_{0:032x}"


def _evaluation(requested: Decimal, approved: Decimal, decision: RiskDecision) -> RiskEvaluation:
    return RiskEvaluation(
        risk_evaluation_id=_oid("re"),
        order_intent_id=_oid("oi"),
        decision_id=_oid("dec"),
        workspace_id=_oid("ws"),
        evaluated_at=AS_OF,
        decision=decision,
        reason_codes=[RiskReasonCode.APPROVED]
        if decision is RiskDecision.APPROVED
        else [RiskReasonCode.APPROVED_RESIZED]
        if decision is RiskDecision.APPROVED_RESIZED
        else [RiskReasonCode.MAX_POSITION_EXCEEDED],
        applied_policy_ids=[_oid("rp")],
        requested_notional=Money(amount=requested, currency="USDT"),
        approved_notional=Money(amount=approved, currency="USDT"),
        evaluator_version="v1",
    )


class TestRiskCannotEnlarge:
    """ADR 0004: the risk engine is a constraint, not an optimiser."""

    @given(requested=amounts, extra=amounts)
    @settings(max_examples=200)
    def test_approving_more_than_requested_is_unrepresentable(
        self, requested: Decimal, extra: Decimal
    ) -> None:
        with pytest.raises(ValidationError):
            _evaluation(requested, requested + extra, RiskDecision.APPROVED)

    @given(requested=amounts)
    @settings(max_examples=200)
    def test_rejection_always_approves_zero(self, requested: Decimal) -> None:
        evaluation = _evaluation(requested, Decimal(0), RiskDecision.REJECTED)
        assert evaluation.approved_notional.is_zero
        assert not evaluation.is_approved

    @given(requested=amounts, fraction=st.decimals(min_value="0.01", max_value="0.99", places=2))
    @settings(max_examples=200)
    def test_any_approval_is_bounded_by_the_request(
        self, requested: Decimal, fraction: Decimal
    ) -> None:
        approved = (requested * fraction).quantize(Decimal("0.00000001"))
        assume(0 < approved < requested)
        evaluation = _evaluation(requested, approved, RiskDecision.APPROVED_RESIZED)
        assert evaluation.approved_notional.amount <= evaluation.requested_notional.amount
        assert evaluation.is_approved


class TestMoneyArithmetic:
    @given(a=signed_amounts, b=signed_amounts, currency=assets)
    @settings(max_examples=300)
    def test_addition_is_commutative_and_exact(self, a: Decimal, b: Decimal, currency: str) -> None:
        x = Money(amount=a, currency=currency)
        y = Money(amount=b, currency=currency)
        assert (x + y) == (y + x)
        assert (x + y).amount == a + b

    @given(a=signed_amounts, currency=assets)
    @settings(max_examples=200)
    def test_subtracting_self_is_zero(self, a: Decimal, currency: str) -> None:
        money = Money(amount=a, currency=currency)
        assert (money - money).is_zero

    @given(a=signed_amounts, b=signed_amounts)
    @settings(max_examples=200)
    def test_cross_currency_arithmetic_always_raises(self, a: Decimal, b: Decimal) -> None:
        with pytest.raises(ValueError, match="cannot combine"):
            Money(amount=a, currency="USD") + Money(amount=b, currency="USDT")

    @given(value=st.floats(allow_nan=False, allow_infinity=False, width=32))
    @settings(max_examples=100)
    def test_floats_are_never_accepted(self, value: float) -> None:
        with pytest.raises(ValidationError):
            Money(amount=value, currency="USD")  # type: ignore[arg-type]

    @given(price=amounts, qty=amounts, base=assets, quote=assets)
    @settings(max_examples=200)
    def test_notional_matches_price_times_quantity(
        self, price: Decimal, qty: Decimal, base: str, quote: str
    ) -> None:
        assume(base != quote)
        p = Price(value=price, base=base, quote=quote)
        notional = p.notional_for(Quantity(value=qty, asset=base))
        assert notional.amount == price * qty
        assert notional.currency == quote


class TestInstrumentIdentity:
    @given(base=assets, quote=assets, venue=venues, cls=st.sampled_from(list(InstrumentClass)))
    @settings(max_examples=300)
    def test_canonical_form_round_trips(
        self, base: str, quote: str, venue: str, cls: InstrumentClass
    ) -> None:
        assume(base != quote)
        instrument = InstrumentId(base=base, quote=quote, venue=venue, instrument_class=cls)
        assert InstrumentId.parse(instrument.value) == instrument

    @given(base=assets, quote=assets, venue=venues)
    @settings(max_examples=100)
    def test_identity_determines_the_hash(self, base: str, quote: str, venue: str) -> None:
        assume(base != quote)
        a = InstrumentId(base=base, quote=quote, venue=venue)
        b = InstrumentId.parse(a.value)
        assert content_hash(a) == content_hash(b)


class TestHashStability:
    @given(
        values=st.dictionaries(st.text(min_size=1, max_size=12), amounts, min_size=1, max_size=8)
    )
    @settings(max_examples=200)
    def test_hash_is_independent_of_insertion_order(self, values: dict[str, Decimal]) -> None:
        reordered = dict(reversed(list(values.items())))
        assert content_hash(values) == content_hash(reordered)

    @given(delta=st.integers(min_value=1, max_value=10_000))
    @settings(max_examples=100)
    def test_distinct_timestamps_hash_differently(self, delta: int) -> None:
        a = AS_OF
        b = AS_OF + timedelta(seconds=delta)
        assert content_hash(a) != content_hash(b)
