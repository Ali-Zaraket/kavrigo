"""Money, quantity and price value objects.

``AGENTS.md`` § Non-negotiable domain rules #6: *money and quantity use decimal/fixed-point
authoritative types, never binary floats.* Binary floating point cannot represent ``0.1``
exactly; accumulating fees, fills and P&L in ``float`` produces balances that disagree with the
venue, and a reconciliation system that disagrees with the venue is worse than none.

Two further defects are guarded here:

* **Silent float coercion.** ``Decimal(0.1)`` is ``0.1000000000000000055511151231257827``.
  Passing a ``float`` anywhere near authoritative money is rejected rather than coerced.
* **Unit confusion.** A bare ``Decimal`` does not say whether it is USD, BTC, or a price. Each
  value object carries its unit and refuses cross-unit arithmetic.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Self

from pydantic import BeforeValidator, Field, model_validator

from kavrigo_domain.base import DomainModel

__all__ = [
    "AssetCode",
    "ExactDecimal",
    "Money",
    "Price",
    "Quantity",
]


def _exact_decimal(value: Any) -> Any:
    """Accept ``Decimal``, ``int`` or ``str``; reject ``float``, NaN and infinity."""
    if isinstance(value, bool):
        # ValueError, not TypeError: Pydantic converts ValueError into a ValidationError, while
        # a TypeError escapes validation and surfaces as an unhandled 500 at the API boundary.
        raise ValueError("bool is not a valid decimal value")
    if isinstance(value, float):
        raise ValueError(
            "binary float is not permitted for money or quantity; "
            "pass a Decimal, int, or string (AGENTS.md domain rule 6)"
        )
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            value = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"not a valid decimal: {value!r}") from exc
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("NaN and infinity are not valid monetary values")
        return value
    return value


ExactDecimal = Annotated[Decimal, BeforeValidator(_exact_decimal)]
"""A ``Decimal`` that refuses binary floats, NaN and infinity."""

AssetCode = Annotated[
    str,
    Field(
        min_length=2,
        max_length=16,
        pattern=r"^[A-Z0-9]{2,16}$",
        description="Uppercase asset or currency code, e.g. BTC, ETH, USDT, USD.",
    ),
]


class Money(DomainModel):
    """An amount in a specific currency.

    Arithmetic is deliberately restrictive: adding USD to USDT is a bug, not a conversion, and
    this type will not quietly perform one.
    """

    amount: ExactDecimal
    currency: AssetCode

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    @classmethod
    def zero(cls, currency: str) -> Self:
        return cls(amount=Decimal(0), currency=currency)

    def _require_same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(
                f"cannot combine {self.currency} with {other.currency}; "
                "convert explicitly with a recorded rate"
            )

    def __add__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __neg__(self) -> Money:
        return Money(amount=-self.amount, currency=self.currency)

    def scaled_by(self, factor: Decimal | int | str) -> Money:
        """Multiply by a dimensionless factor (a ratio, never another Money)."""
        return Money(amount=self.amount * _to_decimal(factor), currency=self.currency)

    def quantize_to(self, exponent: Decimal | str) -> Money:
        """Round explicitly to a venue's currency precision.

        Rounding is never implicit: the caller states where it happens, because rounding in the
        wrong place is how a ledger and a venue drift apart.
        """
        return Money(amount=self.amount.quantize(_to_decimal(exponent)), currency=self.currency)

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    @property
    def is_negative(self) -> bool:
        return self.amount < 0


class Quantity(DomainModel):
    """A quantity of an asset. Negative values represent short exposure."""

    value: ExactDecimal
    asset: AssetCode

    def __str__(self) -> str:
        return f"{self.value} {self.asset}"

    @classmethod
    def zero(cls, asset: str) -> Self:
        return cls(value=Decimal(0), asset=asset)

    def _require_same_asset(self, other: Quantity) -> None:
        if self.asset != other.asset:
            raise ValueError(f"cannot combine quantities of {self.asset} and {other.asset}")

    def __add__(self, other: Quantity) -> Quantity:
        self._require_same_asset(other)
        return Quantity(value=self.value + other.value, asset=self.asset)

    def __sub__(self, other: Quantity) -> Quantity:
        self._require_same_asset(other)
        return Quantity(value=self.value - other.value, asset=self.asset)

    def __neg__(self) -> Quantity:
        return Quantity(value=-self.value, asset=self.asset)

    @property
    def is_zero(self) -> bool:
        return self.value == 0

    def abs(self) -> Quantity:
        return Quantity(value=abs(self.value), asset=self.asset)


class Price(DomainModel):
    """A price expressed as quote currency per one unit of the base asset."""

    value: ExactDecimal
    base: AssetCode
    quote: AssetCode

    def __str__(self) -> str:
        return f"{self.value} {self.quote}/{self.base}"

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.value <= 0:
            raise ValueError("price must be strictly positive")
        if self.base == self.quote:
            raise ValueError("base and quote assets must differ")
        return self

    def notional_for(self, quantity: Quantity) -> Money:
        """Value ``quantity`` of the base asset in the quote currency.

        Refuses to price a quantity of a different asset, which is the failure mode this type
        exists to prevent.
        """
        if quantity.asset != self.base:
            raise ValueError(
                f"cannot value {quantity.asset} using a {self.base}/{self.quote} price"
            )
        return Money(amount=self.value * quantity.value, currency=self.quote)


def _to_decimal(value: Decimal | int | str) -> Decimal:
    result = _exact_decimal(value)
    if not isinstance(result, Decimal):  # pragma: no cover - defensive
        raise TypeError(f"expected a decimal-compatible value, got {type(value)!r}")
    return result
