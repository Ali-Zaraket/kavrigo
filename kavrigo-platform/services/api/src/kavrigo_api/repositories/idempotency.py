"""Idempotency-key storage (``MASTER_BUILD_SPEC.md`` §49, ``AGENTS.md`` domain rule 7).

Retries are normal: a client times out, a proxy retries, a mobile network duplicates a request.
Without this, a retried "create agent" produces two agents, and later — with a real broker — a
retried order produces two orders.

The stored ``request_hash`` is what makes the mechanism safe rather than merely convenient.
Returning a cached response for a *different* body under the same key would be worse than no
idempotency at all, so that case is rejected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kavrigo_api.db.models import IdempotencyKey

__all__ = ["IdempotencyConflict", "IdempotencyRepository", "StoredResponse"]

DEFAULT_RETENTION = timedelta(hours=24)


class IdempotencyConflict(Exception):
    """The key was reused with a different request body."""


class StoredResponse:
    __slots__ = ("body", "status")

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self.body = body


class IdempotencyRepository:
    def __init__(self, session: AsyncSession, workspace_id: str) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def lookup(self, *, key: str, endpoint: str, request_hash: str) -> StoredResponse | None:
        """Return the recorded response for a replayed request.

        Raises :class:`IdempotencyConflict` when the key was used for a different body.
        """
        result = await self._session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.workspace_id == self._workspace_id,
                IdempotencyKey.idempotency_key == key,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        if row.expires_at <= datetime.now(UTC):
            return None
        if row.request_hash != request_hash or row.endpoint != endpoint:
            raise IdempotencyConflict(
                "this idempotency key was already used for a different request"
            )
        return StoredResponse(row.response_status, row.response_body)

    async def store(
        self,
        *,
        key: str,
        endpoint: str,
        request_hash: str,
        status: int,
        body: dict[str, Any],
        retention: timedelta = DEFAULT_RETENTION,
    ) -> None:
        self._session.add(
            IdempotencyKey(
                workspace_id=self._workspace_id,
                idempotency_key=key,
                endpoint=endpoint,
                request_hash=request_hash,
                response_status=status,
                response_body=body,
                expires_at=datetime.now(UTC) + retention,
            )
        )
        await self._session.flush()

    async def purge_expired(self) -> int:
        result = await self._session.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.workspace_id == self._workspace_id,
                IdempotencyKey.expires_at <= datetime.now(UTC),
            )
        )
        return cast("CursorResult[Any]", result).rowcount
