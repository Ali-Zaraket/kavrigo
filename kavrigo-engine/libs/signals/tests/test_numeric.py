"""Deterministic arithmetic primitives."""

from __future__ import annotations

from decimal import Decimal, getcontext, localcontext

import pytest

from kavrigo_signals import FEATURE_CONTEXT, mean, safe_divide, stdev, to_bps


class TestDeterminism:
    def test_results_do_not_depend_on_the_ambient_decimal_context(self) -> None:
        """The whole point of a fixed context.

        A library that changed the process-global precision would otherwise silently change
        every recorded feature value.
        """
        values = [Decimal("1"), Decimal("2"), Decimal("4"), Decimal("8")]
        baseline = stdev(values)
        with localcontext() as ctx:
            ctx.prec = 6
            assert stdev(values) == baseline
        with localcontext() as ctx:
            ctx.prec = 50
            assert stdev(values) == baseline

    def test_the_context_precision_is_pinned(self) -> None:
        assert FEATURE_CONTEXT.prec == 28

    def test_arithmetic_is_exact_where_float_would_not_be(self) -> None:
        assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")
        # Documents the defect the decimal types exist to avoid.
        assert 0.1 + 0.2 != 0.3

    def test_the_ambient_context_is_left_alone(self) -> None:
        before = getcontext().prec
        stdev([Decimal("1"), Decimal("2")])
        assert getcontext().prec == before


class TestSafeDivide:
    def test_a_zero_denominator_is_unknown_not_zero(self) -> None:
        """Zero would be a specific, wrong claim; unknown drives abstention."""
        assert safe_divide(Decimal("1"), Decimal("0")) is None

    def test_ordinary_division(self) -> None:
        assert safe_divide(Decimal("3"), Decimal("4")) == Decimal("0.75")


class TestMeanAndStdev:
    def test_mean_of_an_empty_sample_is_none(self) -> None:
        assert mean([]) is None

    def test_mean_is_exact(self) -> None:
        assert mean([Decimal("1"), Decimal("2"), Decimal("3")]) == Decimal("2")

    def test_stdev_needs_two_observations(self) -> None:
        assert stdev([]) is None
        assert stdev([Decimal("5")]) is None

    def test_stdev_uses_the_sample_form(self) -> None:
        """Bessel-corrected: the population form biases volatility downward, which would make a
        strategy look safer than it is.

        For [2, 4, 4, 4, 5, 5, 7, 9] the population sd is 2 and the sample sd is sqrt(32/7).
        """
        values = [Decimal(v) for v in (2, 4, 4, 4, 5, 5, 7, 9)]
        result = stdev(values)
        assert result is not None
        expected = FEATURE_CONTEXT.sqrt(Decimal(32) / Decimal(7))
        assert result == expected
        assert result != Decimal(2)

    def test_stdev_of_identical_values_is_zero(self) -> None:
        assert stdev([Decimal("3"), Decimal("3"), Decimal("3")]) == 0


class TestBps:
    @pytest.mark.parametrize(
        ("ratio", "expected"),
        [("0.0001", "1"), ("0.01", "100"), ("0", "0"), ("-0.0005", "-5")],
    )
    def test_conversion(self, ratio: str, expected: str) -> None:
        assert to_bps(Decimal(ratio)) == Decimal(expected)
