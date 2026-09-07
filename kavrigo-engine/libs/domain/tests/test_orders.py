"""Order intents, approvals, orders and fills."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kavrigo_domain import (
    ApprovedOrderIntent,
    Fill,
    InstrumentId,
    LiquidityFlag,
    Money,
    Order,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    Price,
    Quantity,
    TimeInForce,
    TradingMode,
)
from kavrigo_domain.testing import AS_OF, oid

BTC = InstrumentId.parse("BTC-USDT.BINANCE")


def _intent(**overrides: object) -> OrderIntent:
    base: dict[str, object] = {
        "order_intent_id": oid("oi"),
        "decision_id": oid("dec"),
        "workspace_id": oid("ws"),
        "agent_version_id": oid("av"),
        "instrument_id": BTC,
        "mode": TradingMode.PAPER,
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "notional": Money(amount="500", currency="USDT"),
        "idempotency_key": "idem-0000000001",
        "created_at": AS_OF,
        "expires_at": AS_OF + timedelta(minutes=1),
    }
    return OrderIntent(**{**base, **overrides})  # type: ignore[arg-type]


class TestLiveGate:
    def test_live_intents_cannot_be_constructed(self) -> None:
        with pytest.raises(ValidationError, match="live order intents are not constructible"):
            _intent(mode=TradingMode.LIVE)

    def test_live_approved_intents_cannot_be_constructed(self) -> None:
        with pytest.raises(ValidationError, match="live execution is gated"):
            ApprovedOrderIntent(
                order_intent_id=oid("oi"),
                risk_evaluation_id=oid("re"),
                workspace_id=oid("ws"),
                instrument_id=BTC,
                mode=TradingMode.LIVE,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                approved_notional=Money(amount="500", currency="USDT"),
                time_in_force=TimeInForce.IOC,
                client_order_id="kvg-00000001",
                fencing_token=1,
                approved_at=AS_OF,
                expires_at=AS_OF + timedelta(minutes=1),
            )


class TestIntentValidation:
    def test_non_spot_instruments_are_refused(self) -> None:
        perp = InstrumentId.parse("BTC-USDT.BINANCE:perpetual")
        with pytest.raises(ValidationError, match="spot instruments only"):
            _intent(instrument_id=perp)

    def test_notional_currency_must_be_the_quote_currency(self) -> None:
        with pytest.raises(ValidationError, match="must be the instrument's quote currency"):
            _intent(notional=Money(amount="500", currency="USD"))

    def test_limit_order_requires_a_price(self) -> None:
        with pytest.raises(ValidationError, match="limit order requires a limit price"):
            _intent(order_type=OrderType.LIMIT)

    def test_market_order_must_not_carry_a_price(self) -> None:
        with pytest.raises(ValidationError, match="must not carry a limit price"):
            _intent(limit_price=Price(value="60000", base="BTC", quote="USDT"))

    def test_limit_price_assets_must_match_the_instrument(self) -> None:
        with pytest.raises(ValidationError, match="limit price assets do not match"):
            _intent(
                order_type=OrderType.LIMIT,
                limit_price=Price(value="3000", base="ETH", quote="USDT"),
            )

    def test_negative_notional_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="notional must be positive"):
            _intent(notional=Money(amount="-500", currency="USDT"))

    def test_intents_expire(self) -> None:
        intent = _intent()
        assert not intent.is_expired_at(AS_OF)
        assert intent.is_expired_at(AS_OF + timedelta(minutes=2))

    def test_expiry_must_follow_creation(self) -> None:
        with pytest.raises(ValidationError, match="expires_at must be after created_at"):
            _intent(expires_at=AS_OF)


class TestFills:
    def _fill(self, **overrides: object) -> Fill:
        base: dict[str, object] = {
            "fill_id": oid("fill"),
            "order_id": oid("ord"),
            "workspace_id": oid("ws"),
            "instrument_id": BTC,
            "side": OrderSide.BUY,
            "quantity": Quantity(value="0.01", asset="BTC"),
            "price": Price(value="60000", base="BTC", quote="USDT"),
            "fee": Money(amount="0.6", currency="USDT"),
            "liquidity": LiquidityFlag.TAKER,
            "venue_timestamp": AS_OF,
            "recorded_at": AS_OF,
        }
        return Fill(**{**base, **overrides})  # type: ignore[arg-type]

    def test_notional_is_computed_exactly(self) -> None:
        assert self._fill().notional == Money(amount=Decimal("600.00"), currency="USDT")

    def test_quantity_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="quantity must be positive"):
            self._fill(quantity=Quantity(value="-0.01", asset="BTC"))

    def test_quantity_asset_must_be_the_base_asset(self) -> None:
        with pytest.raises(ValidationError, match="must be the instrument's base asset"):
            self._fill(quantity=Quantity(value="0.01", asset="ETH"))

    def test_negative_fees_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="fee must not be negative"):
            self._fill(fee=Money(amount="-0.1", currency="USDT"))


class TestOrderState:
    def _order(self, **overrides: object) -> Order:
        base: dict[str, object] = {
            "order_id": oid("ord"),
            "client_order_id": "kvg-00000001",
            "order_intent_id": oid("oi"),
            "workspace_id": oid("ws"),
            "instrument_id": BTC,
            "mode": TradingMode.PAPER,
            "side": OrderSide.BUY,
            "order_type": OrderType.MARKET,
            "status": OrderStatus.ACCEPTED,
            "requested_notional": Money(amount="600", currency="USDT"),
            "filled_quantity": Quantity.zero("BTC"),
            "fees_paid": Money.zero("USDT"),
            "last_updated_at": AS_OF,
        }
        return Order(**{**base, **overrides})  # type: ignore[arg-type]

    def test_unknown_is_a_representable_state(self) -> None:
        """A timeout after submission must be recordable, not guessed away."""
        order = self._order(status=OrderStatus.UNKNOWN)
        assert not order.status.is_terminal
        assert order.status is OrderStatus.UNKNOWN

    def test_filled_orders_need_a_quantity(self) -> None:
        with pytest.raises(ValidationError, match="FILLED order must have a non-zero"):
            self._order(status=OrderStatus.FILLED)

    def test_rejected_orders_cannot_have_fills(self) -> None:
        with pytest.raises(ValidationError, match="REJECTED order cannot have fills"):
            self._order(
                status=OrderStatus.REJECTED,
                filled_quantity=Quantity(value="0.01", asset="BTC"),
            )

    def test_fills_must_sum_to_the_filled_quantity(self) -> None:
        order_id = oid("ord")
        fills = [
            Fill(
                fill_id=oid("fill", n),
                order_id=order_id,
                workspace_id=oid("ws"),
                instrument_id=BTC,
                side=OrderSide.BUY,
                quantity=Quantity(value="0.005", asset="BTC"),
                price=Price(value="60000", base="BTC", quote="USDT"),
                fee=Money(amount="0.3", currency="USDT"),
                venue_timestamp=AS_OF,
                recorded_at=AS_OF,
            )
            for n in (1, 2)
        ]
        with pytest.raises(ValidationError, match="does not match the sum of fills"):
            self._order(
                order_id=order_id,
                status=OrderStatus.PARTIALLY_FILLED,
                filled_quantity=Quantity(value="0.02", asset="BTC"),
                fills=fills,
            )

        ok = self._order(
            order_id=order_id,
            status=OrderStatus.FILLED,
            filled_quantity=Quantity(value="0.01", asset="BTC"),
            fills=fills,
        )
        assert ok.status.is_terminal

    def test_open_and_terminal_states_are_disjoint(self) -> None:
        for status in OrderStatus:
            assert not (status.is_open and status.is_terminal)
