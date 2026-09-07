"""Deterministic factories for tests and fixtures.

Shipped with the package rather than hidden in a test directory so that every service — and
later, every repository in the split — builds valid domain objects the same way. Values are
deterministic: a test that fails should fail for a reason, not because a random id changed.

This module contains no credentials, no network access, and nothing that reaches a venue.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["AS_OF", "HASH", "oid"]

AS_OF = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
"""A fixed decision time. Point-in-time correctness is easier to reason about with a constant."""

HASH = "sha256:" + "ab" * 32
"""A syntactically valid placeholder content hash."""


def oid(prefix: str, n: int = 1) -> str:
    """Deterministic prefixed identifier, e.g. ``oid("dec") -> 'dec_000...001'``."""
    return f"{prefix}_{n:032x}"
