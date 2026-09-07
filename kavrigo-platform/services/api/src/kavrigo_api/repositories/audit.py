"""Append-only audit writes (``MASTER_BUILD_SPEC.md`` §25, §53).

There is no update or delete method here, and the database refuses both anyway. Privileged and
high-impact actions record actor, timestamp and reason.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from kavrigo_api.db.models import AuditEvent

__all__ = ["AuditRepository"]


class AuditRepository:
    def __init__(self, session: AsyncSession, workspace_id: str) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def record(
        self,
        *,
        action: str,
        actor: str,
        subject_type: str | None = None,
        subject_id: str | None = None,
        reason: str = "",
        request_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Append one audit event and return its id.

        Written in the same transaction as the change it describes, so an action cannot be
        committed without its audit record.
        """
        audit_id = f"aud_{uuid.uuid4().hex}"
        self._session.add(
            AuditEvent(
                audit_id=audit_id,
                workspace_id=self._workspace_id,
                action=action,
                actor=actor,
                reason=reason,
                subject_type=subject_type,
                subject_id=subject_id,
                request_id=request_id,
                payload=payload or {},
            )
        )
        await self._session.flush()
        return audit_id
