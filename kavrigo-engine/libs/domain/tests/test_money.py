"""Money, Quantity and Price: the types that guard authoritative accounting."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from kavrigo_domain import Money, Price, Quantity


class TestFloatRejection:
    """``AGENTS.md`` domain rule 6: never binary floats for money or quantity."""

    def test_float_amount_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="binary float is not permitted"):
            Money(amount=0.1, currency="USD")  # type: ignore[arg-type]

    def test_float_quantity_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="binary float is not permitted"):
            Quantity(value=1.5, asset="BTC")  # type: ignore[arg-type]

    def test_bool_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Money(amount=True, currency="USD")  # type: ignore[arg-type]

    def test_string_and_int_are_accepted_exactly(self) -> None:
        assert Money(amount="0.1", currency="USD").amount == Decimal("0.1")
        assert Money(amount=5, currency="USD").amount == Decimal(5)

    def test_nan_and_infinity_are_rejected(self) -> None:
        for bad in ("NaN", "Infinity", "-Infinity"):
            with pytest.raises(ValidationError):
                Money(amount=bad, currency="USD")


class TestMoneyArithmetic:
    def test_addition_is_exact(self) -> None:
        total = Money(amount="0.1", currency="USD") + Money(amount="0.2", currency="USD")
        assert total.amount == Decimal("0.3")

    def test_cross_currency_addition_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot combine USD with USDT"):
            Money(amount="1", currency="USD") + Money(amount="1", currency="USDT")

    def test_scaling_by_a_ratio(self) -> None:
        assert Money(amount="100", currency="USD").scaled_by("0.25").amount == Decimal("25.00")

    def test_quantize_is_explicit(self) -> None:
        rounded = Money(amount="1.23456", currency="USD").quantize_to("0.01")
        assert rounded.amount == Decimal("1.23")

    def test_models_are_frozen(self) -> None:
        money = Money(amount="1", currency="USD")
        with pytest.raises(ValidationError):
            money.amount = Decimal("2")  # type: ignore[misc]


class TestQuantity:
    def test_cross_asset_addition_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot combine quantities"):
            Quantity(value="1", asset="BTC") + Quantity(value="1", asset="ETH")

    def test_negative_quantity_is_allowed_for_short_exposure(self) -> None:
        assert Quantity(value="-1", asset="BTC").value == Decimal(-1)


class TestPrice:
    def test_price_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="strictly positive"):
            Price(value="0", base="BTC", quote="USDT")

    def test_notional_requires_the_matching_base_asset(self) -> None:
        price = Price(value="60000", base="BTC", quote="USDT")
        with pytest.raises(ValueError, match="cannot value ETH"):
            price.notional_for(Quantity(value="1", asset="ETH"))

    def test_notional_is_exact(self) -> None:
        price = Price(value="60000.55", base="BTC", quote="USDT")
        notional = price.notional_for(Quantity(value="0.5", asset="BTC"))
        assert notional == Money(amount=Decimal("30000.275"), currency="USDT")
