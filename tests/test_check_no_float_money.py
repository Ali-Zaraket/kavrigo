"""Tests for the pre-commit guard that keeps binary floats out of monetary fields."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_no_float_money.py"
_spec = importlib.util.spec_from_file_location("check_no_float_money", _SCRIPT)
assert _spec is not None
assert _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
sys.modules["check_no_float_money"] = guard
_spec.loader.exec_module(guard)


def _write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(source)
    return path


def test_flags_a_float_monetary_field(tmp_path: Path) -> None:
    path = _write(tmp_path, "class Order:\n    notional_usd: float\n")
    problems = guard.check(path)
    assert len(problems) == 1
    assert "Order.notional_usd" in problems[0]


def test_flags_an_optional_float_quantity(tmp_path: Path) -> None:
    path = _write(tmp_path, "class Position:\n    quantity: float | None\n")
    assert len(guard.check(path)) == 1


def test_allows_decimal_monetary_fields(tmp_path: Path) -> None:
    path = _write(tmp_path, "class Order:\n    notional_usd: ExactDecimal\n")
    assert guard.check(path) == []


def test_allows_bounded_scores_in_score_containers(tmp_path: Path) -> None:
    """``SignalScores.price`` is a signal in [-1, 1], not a price."""
    path = _write(tmp_path, "class SignalScores:\n    price: float\n")
    assert guard.check(path) == []


def test_allows_explicitly_named_scores_anywhere(tmp_path: Path) -> None:
    path = _write(tmp_path, "class Prediction:\n    confidence: float\n")
    assert guard.check(path) == []


def test_flags_module_level_annotations_once(tmp_path: Path) -> None:
    path = _write(tmp_path, "default_notional: float = 0.0\n")
    assert len(guard.check(path)) == 1


def test_class_fields_are_not_reported_twice(tmp_path: Path) -> None:
    path = _write(tmp_path, "class Order:\n    fee: float\n")
    assert len(guard.check(path)) == 1


def test_the_real_domain_package_is_clean() -> None:
    """The guard must agree with the contracts it protects."""
    domain = Path(__file__).resolve().parents[1] / "kavrigo-engine/libs/domain/src/kavrigo_domain"
    problems = [p for f in sorted(domain.glob("*.py")) for p in guard.check(f)]
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize(
    ("exit_code", "source"),
    [(0, "x: int = 1\n"), (1, "price: float = 1.0\n")],
)
def test_main_exit_codes(tmp_path: Path, exit_code: int, source: str) -> None:
    path = _write(tmp_path, source)
    assert guard.main([str(path)]) == exit_code
