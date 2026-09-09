"""Bounded integer arithmetic: 12 decimal places, no ambient Decimal rounding.

Money/price/quantity inputs outside this local slice's range fail closed. Exposure products
must be exactly representable; an unrepresentable account valuation is never rounded down.
"""

from decimal import Decimal

SCALE = 10**12
MAX_UNITS = 10**30
BPS_DENOMINATOR = 10_000 * SCALE


def units(value: Decimal) -> int:
    if not value.is_finite() or abs(value.adjusted()) > 40:
        raise ValueError("unsupported fixed-point range")
    numerator, denominator = value.as_integer_ratio()
    result, remainder = divmod(numerator * SCALE, denominator)
    if remainder or abs(result) > MAX_UNITS:
        raise ValueError("value must fit 12 decimal places and magnitude 10^18")
    return result


def decimal(value: int) -> Decimal:
    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), SCALE)
    return Decimal(f"{sign}{whole}.{fraction:012d}")


def ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def product(left: int, right: int) -> int:
    result, remainder = divmod(left * right, SCALE)
    if remainder or abs(result) > MAX_UNITS:
        raise ValueError("portfolio valuation is not exactly representable")
    return result
