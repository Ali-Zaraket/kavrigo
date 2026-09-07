"""Timestamp discipline and canonical hashing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kavrigo_domain import DomainModel, Money, UtcDatetime, canonical_json, content_hash


class _Sample(DomainModel):
    at: UtcDatetime


class TestUtcDatetime:
    def test_naive_datetime_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="naive datetime"):
            _Sample(at=datetime(2026, 3, 1, 12, 0, 0))  # noqa: DTZ001

    def test_offset_datetime_is_normalised_to_utc(self) -> None:
        aware = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        assert _Sample(at=aware).at == datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)

    def test_iso_string_with_offset_is_accepted(self) -> None:
        assert _Sample(at="2026-03-01T12:00:00+00:00").at == datetime(2026, 3, 1, 12, tzinfo=UTC)

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _Sample(at="2026-03-01T12:00:00Z", surprise=1)  # type: ignore[call-arg]


class TestHashing:
    def test_hash_is_stable_across_key_order(self) -> None:
        assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})

    def test_decimals_normalise_before_hashing(self) -> None:
        assert content_hash(Decimal("1.10")) == content_hash(Decimal("1.1"))

    def test_models_hash_by_value(self) -> None:
        a = Money(amount="1.50", currency="USD")
        b = Money(amount="1.5", currency="USD")
        assert content_hash(a) == content_hash(b)

    def test_bounded_score_floats_hash_deterministically(self) -> None:
        """Scores are floats by design; money never is. The hash only has to be stable."""
        assert content_hash({"confidence": 0.65}) == content_hash({"confidence": 0.65})
        assert content_hash({"confidence": 0.65}) != content_hash({"confidence": 0.66})

    def test_non_finite_floats_cannot_be_hashed(self) -> None:
        with pytest.raises(ValueError, match="cannot hash NaN or infinity"):
            content_hash({"value": float("nan")})

    def test_naive_datetime_cannot_be_hashed(self) -> None:
        with pytest.raises(ValueError, match="naive datetime"):
            content_hash(datetime(2026, 3, 1))  # noqa: DTZ001

    def test_hash_is_algorithm_prefixed(self) -> None:
        assert content_hash({"a": 1}).startswith("sha256:")

    def test_canonical_json_has_no_insignificant_whitespace(self) -> None:
        assert canonical_json({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'
