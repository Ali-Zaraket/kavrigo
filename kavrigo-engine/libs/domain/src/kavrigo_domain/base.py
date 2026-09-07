"""Shared Pydantic base types for every Kavrigo domain contract.

Two properties matter more than convenience here:

* **Immutability.** Runs reference immutable versions (``MASTER_BUILD_SPEC.md`` §3). A decision,
  an evidence item and a snapshot describe what was true at a point in time; mutating one
  silently rewrites history, so every domain model is frozen.
* **Strictness.** ``extra="forbid"`` means an unexpected field from a provider payload or a model
  response is an error, not a silently ignored key. Unvalidated model JSON must never enter the
  domain (``AGENTS.md`` § Engineering rules).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict

__all__ = ["DomainModel", "UtcDatetime", "utc_now"]


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime.

    Always use this rather than ``datetime.now()``; naive local timestamps in a trading system
    produce silently wrong freshness and ordering decisions.
    """
    return datetime.now(UTC)


def _require_utc(value: Any) -> Any:
    """Reject naive datetimes and normalise aware ones to UTC.

    A naive datetime is ambiguous: freshness checks, event ordering and point-in-time backtests
    all depend on knowing the offset, so guessing one is worse than failing.
    """
    if isinstance(value, str):
        # Let Pydantic parse ISO-8601 first, then re-validate the result.
        parsed = datetime.fromisoformat(value)
        value = parsed
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(
                "naive datetime is not allowed; provide a timezone-aware UTC timestamp"
            )
        return value.astimezone(UTC)
    return value


UtcDatetime = Annotated[datetime, BeforeValidator(_require_utc)]
"""A timezone-aware datetime normalised to UTC. Naive datetimes are rejected."""


class DomainModel(BaseModel):
    """Frozen, strict base model for domain contracts."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
        use_enum_values=False,
        ser_json_timedelta="iso8601",
    )
