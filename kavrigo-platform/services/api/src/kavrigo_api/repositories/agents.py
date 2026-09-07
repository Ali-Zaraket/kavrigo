"""Agent and agent-version access.

Every query is workspace-scoped explicitly, and runs inside an RLS-scoped session.
``agent_versions`` is append-only in the database, so this repository offers no update or delete
path for it — the absence is the design.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kavrigo_api.db.models import Agent, AgentVersionRow

__all__ = ["AgentRepository", "decode_cursor", "encode_cursor", "new_agent_id", "new_version_id"]


def new_agent_id() -> str:
    return f"ag_{uuid.uuid4().hex}"


def new_version_id() -> str:
    return f"av_{uuid.uuid4().hex}"


def encode_cursor(value: str) -> str:
    """Opaque cursor. Clients must not construct these."""
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> str | None:
    """Decode a cursor, returning ``None`` if it is malformed.

    A bad cursor is a client error, not a server error, and must not surface a decoding
    exception from an untrusted string.
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return base64.urlsafe_b64decode(padded.encode()).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None


class AgentRepository:
    def __init__(self, session: AsyncSession, workspace_id: str) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def get_agent(self, agent_id: str) -> Agent | None:
        result = await self._session.execute(
            select(Agent).where(
                Agent.agent_id == agent_id, Agent.workspace_id == self._workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def get_agent_by_name(self, name: str) -> Agent | None:
        result = await self._session.execute(
            select(Agent).where(Agent.name == name, Agent.workspace_id == self._workspace_id)
        )
        return result.scalar_one_or_none()

    async def list_agents(
        self, *, limit: int, after_agent_id: str | None = None, include_archived: bool = False
    ) -> list[Agent]:
        stmt = select(Agent).where(Agent.workspace_id == self._workspace_id)
        if not include_archived:
            stmt = stmt.where(Agent.archived_at.is_(None))
        if after_agent_id is not None:
            stmt = stmt.where(Agent.agent_id > after_agent_id)
        # Ordering by the primary key makes the cursor total and stable; ordering by created_at
        # alone would be ambiguous for rows written in the same transaction.
        stmt = stmt.order_by(Agent.agent_id).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def create_agent(self, *, name: str, description: str, created_by: str) -> Agent:
        agent = Agent(
            agent_id=new_agent_id(),
            workspace_id=self._workspace_id,
            name=name,
            description=description,
            current_version=0,
            created_by=created_by,
        )
        self._session.add(agent)
        await self._session.flush()
        return agent

    async def archive_agent(self, agent_id: str) -> bool:
        """Archive rather than delete: historical decisions must remain explicable."""
        result = await self._session.execute(
            update(Agent)
            .where(
                Agent.agent_id == agent_id,
                Agent.workspace_id == self._workspace_id,
                Agent.archived_at.is_(None),
            )
            .values(archived_at=datetime.now(UTC))
        )
        return cast("CursorResult[Any]", result).rowcount > 0

    async def next_version_number(self, agent_id: str) -> int:
        """The next version number for an agent.

        Taken under the row lock acquired by :meth:`lock_agent` so two concurrent edits cannot
        both claim the same number and collide on the unique constraint.
        """
        result = await self._session.execute(
            select(Agent.current_version).where(
                Agent.agent_id == agent_id, Agent.workspace_id == self._workspace_id
            )
        )
        current = result.scalar_one_or_none()
        return (current or 0) + 1

    async def lock_agent(self, agent_id: str) -> Agent | None:
        """Select the agent row ``FOR UPDATE`` to serialise version creation."""
        result = await self._session.execute(
            select(Agent)
            .where(Agent.agent_id == agent_id, Agent.workspace_id == self._workspace_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def insert_version(
        self,
        *,
        agent_id: str,
        version: int,
        spec: dict[str, Any],
        spec_hash: str,
        prompt_version_id: str,
        prompt_hash: str,
        feature_set_version: str,
        created_by: str,
        author_kind: str,
        change_summary: str,
    ) -> AgentVersionRow:
        row = AgentVersionRow(
            agent_version_id=new_version_id(),
            agent_id=agent_id,
            workspace_id=self._workspace_id,
            version=version,
            spec=spec,
            spec_hash=spec_hash,
            prompt_version_id=prompt_version_id,
            prompt_hash=prompt_hash,
            feature_set_version=feature_set_version,
            created_by=created_by,
            author_kind=author_kind,
            change_summary=change_summary,
            approved_environments=[],
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def set_current_version(self, agent_id: str, version: int) -> None:
        await self._session.execute(
            update(Agent)
            .where(Agent.agent_id == agent_id, Agent.workspace_id == self._workspace_id)
            .values(current_version=version)
        )

    async def get_version(self, agent_id: str, version: int) -> AgentVersionRow | None:
        result = await self._session.execute(
            select(AgentVersionRow).where(
                AgentVersionRow.agent_id == agent_id,
                AgentVersionRow.version == version,
                AgentVersionRow.workspace_id == self._workspace_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_versions(
        self, agent_id: str, *, limit: int, before_version: int | None = None
    ) -> list[AgentVersionRow]:
        stmt = select(AgentVersionRow).where(
            AgentVersionRow.agent_id == agent_id,
            AgentVersionRow.workspace_id == self._workspace_id,
        )
        if before_version is not None:
            stmt = stmt.where(AgentVersionRow.version < before_version)
        stmt = stmt.order_by(AgentVersionRow.version.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())
