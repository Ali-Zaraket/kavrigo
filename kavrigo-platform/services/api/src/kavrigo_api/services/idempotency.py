"""Idempotent handling of state-changing requests.

``AGENTS.md`` domain rule 7: every high-impact mutation supports idempotency. A client retry
after a timeout must not create a second agent — and later, must not place a second order.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from pydantic import BaseModel

from kavrigo_api.errors import ApiError, ErrorCode
from kavrigo_api.repositories.idempotency import (
    IdempotencyConflict,
    IdempotencyRepository,
    StoredResponse,
)
from kavrigo_domain import content_hash

__all__ = ["idempotency_key_from", "replay_or_none", "request_fingerprint", "store_result"]

IDEMPOTENCY_HEADER = "idempotency-key"


def idempotency_key_from(request: Request) -> str | None:
    key = request.headers.get(IDEMPOTENCY_HEADER)
    if key is None:
        return None
    key = key.strip()
    if not key:
        return None
    if len(key) > 128:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "Idempotency-Key must be at most 128 characters.",
            http_status=400,
        )
    return key


def request_fingerprint(body: BaseModel) -> str:
    """Canonical hash of the request body.

    Reusing a key with a different body must be rejected rather than silently returning the
    earlier response — that would be worse than having no idempotency at all.
    """
    return content_hash(body.model_dump(mode="json"))


async def replay_or_none(
    repo: IdempotencyRepository, *, key: str | None, endpoint: str, fingerprint: str
) -> StoredResponse | None:
    if key is None:
        return None
    try:
        return await repo.lookup(key=key, endpoint=endpoint, request_hash=fingerprint)
    except IdempotencyConflict as exc:
        raise ApiError(
            ErrorCode.IDEMPOTENCY_KEY_REUSED,
            "This Idempotency-Key was already used for a different request.",
            http_status=409,
        ) from exc


async def store_result(
    repo: IdempotencyRepository,
    *,
    key: str | None,
    endpoint: str,
    fingerprint: str,
    status: int,
    body: dict[str, Any],
) -> None:
    if key is None:
        return
    await repo.store(key=key, endpoint=endpoint, request_hash=fingerprint, status=status, body=body)
