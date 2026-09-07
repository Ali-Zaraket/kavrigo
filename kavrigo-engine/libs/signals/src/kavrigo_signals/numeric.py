"""Deterministic decimal arithmetic for feature computation.

Every feature must produce the same value on every machine, in a backtest and in a live run
(``MASTER_BUILD_SPEC.md`` §12.2). Two things threaten that, and both are handled here rather
than left to chance:

* **Binary floats.** ``0.1 + 0.2 != 0.3``, and accumulated over a window the drift is large
  enough to flip a threshold comparison. Features feed sizing and risk checks, so they are
  ``Decimal`` throughout.
* **Ambiguous precision.** ``Decimal`` results depend on the *active context*, which is
  process-global and mutable. A library that changed ``getcontext().prec`` would silently change
  every feature value. All arithmetic here runs inside an explicit, fixed context instead.

``ROUND_HALF_EVEN`` is the default and is kept: it is unbiased over many roundings, where
``ROUND_HALF_UP`` accumulates a systematic upward drift.

Fixed precision is deterministic, not exact. Irrational intermediates — ``ln`` in realized
volatility, ``sqrt`` in a standard deviation — round to 28 digits, so a series of identical log
returns yields a dispersion around 1e-28 rather than a clean zero. That residue is reproducible
on every machine, which is what matters here; consumers comparing against zero should compare
against a tolerance.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, InvalidOperation
from typing import Final

__all__ = [
    "FEATURE_CONTEXT",
    "mean",
    "safe_divide",
    "stdev",
    "to_bps",
]

#: Fixed arithmetic context for every feature computation. 28 significant digits is ample for
#: prices and quantities, and pinning it here means no other library's context changes can
#: alter a recorded feature value.
FEATURE_CONTEXT: Final[Context] = Context(prec=28, rounding=ROUND_HALF_EVEN)

_ZERO = Decimal(0)


def safe_divide(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Divide, returning ``None`` when the result is undefined.

    ``None`` rather than zero: a ratio with a zero denominator is *unknown*, and zero is a
    specific, wrong claim. Downstream, an unknown feature causes abstention; a fabricated zero
    would cause a trade.
    """
    if denominator == 0:
        return None
    try:
        return FEATURE_CONTEXT.divide(numerator, denominator)
    except (DivisionByZero, InvalidOperation):  # pragma: no cover - guarded above
        return None


def mean(values: Sequence[Decimal]) -> Decimal | None:
    """Arithmetic mean, or ``None`` for an empty sample."""
    if not values:
        return None
    total = _ZERO
    for value in values:
        total = FEATURE_CONTEXT.add(total, value)
    return safe_divide(total, Decimal(len(values)))


def stdev(values: Sequence[Decimal]) -> Decimal | None:
    """Sample standard deviation (Bessel-corrected), or ``None`` below two observations.

    The sample form (``n - 1``) rather than the population form: a feature window is a sample of
    an ongoing process, not the whole population, and the population form biases volatility
    downward — which would make a strategy look safer than it is.
    """
    if len(values) < 2:
        return None
    sample_mean = mean(values)
    if sample_mean is None:  # pragma: no cover - guarded by the length check
        return None
    total = _ZERO
    for value in values:
        deviation = FEATURE_CONTEXT.subtract(value, sample_mean)
        total = FEATURE_CONTEXT.add(total, FEATURE_CONTEXT.multiply(deviation, deviation))
    variance = safe_divide(total, Decimal(len(values) - 1))
    if variance is None or variance < 0:  # pragma: no cover - variance is a sum of squares
        return None
    return FEATURE_CONTEXT.sqrt(variance)


def to_bps(ratio: Decimal) -> Decimal:
    """Convert a ratio to basis points — the unit risk policy and cost models compare in."""
    return FEATURE_CONTEXT.multiply(ratio, Decimal(10_000))
