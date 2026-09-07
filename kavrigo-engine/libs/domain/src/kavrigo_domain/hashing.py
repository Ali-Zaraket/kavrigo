"""Canonical hashing for reproducibility.

``MASTER_BUILD_SPEC.md`` §25 requires that every decision be reconstructable, which means the
audit ledger stores hashes of the prompt, the feature vector, tool results and the agent spec.
A hash is only useful if it is stable, so serialisation is canonical: sorted keys, no
insignificant whitespace, decimals as strings, datetimes as UTC ISO-8601.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel

__all__ = ["canonical_json", "content_hash", "model_hash"]


def _canonicalise(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonicalise(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {
            str(k): _canonicalise(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, str | bytes):
        return value.decode() if isinstance(value, bytes) else value
    if isinstance(value, Sequence):
        return [_canonicalise(v) for v in value]
    if isinstance(value, Decimal):
        # Normalise so that Decimal("1.10") and Decimal("1.1") hash identically.
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("cannot hash a naive datetime")
        return value.isoformat()
    if isinstance(value, Enum):
        return _canonicalise(value.value)
    if isinstance(value, float):
        # Bounded scores are floats by design; money never is (see money.ExactDecimal). repr()
        # is the shortest representation that round-trips, so the encoding is stable.
        if value != value or value in (float("inf"), float("-inf")):  # NaN or infinity
            raise ValueError("cannot hash NaN or infinity")
        return repr(value)
    return value


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding used for every content hash."""
    return json.dumps(
        _canonicalise(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def content_hash(value: Any) -> str:
    """SHA-256 of the canonical encoding, prefixed with the algorithm.

    The prefix is not decoration: it lets a future algorithm change be detected rather than
    producing silently incomparable hashes in old audit records.
    """
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def model_hash(model: BaseModel) -> str:
    """Content hash of a Pydantic model."""
    return content_hash(model)
