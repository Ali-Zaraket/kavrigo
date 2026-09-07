"""Agent lifecycle and immutable versioning (``MASTER_BUILD_SPEC.md`` §3, §38).

The rule this service exists to enforce: **editing an agent creates a new version; it never
mutates the configuration that produced historical decisions.** There is deliberately no
``update_spec`` method — the only way to change behaviour is :meth:`AgentService.create_version`.
"""

from __future__ import annotations

import uuid
from typing import Any

from kavrigo_api.db.models import Agent, AgentVersionRow
from kavrigo_api.repositories.agents import AgentRepository
from kavrigo_api.repositories.audit import AuditRepository
from kavrigo_api.services.prompts import (
    DEFAULT_PROMPT_VERSION,
    default_prompt_hash,
)
from kavrigo_domain import AgentSpec, AuthorKind, content_hash

__all__ = [
    "DEFAULT_FEATURE_SET_VERSION",
    "AgentArchived",
    "AgentNameTaken",
    "AgentNotFound",
    "AgentService",
]

DEFAULT_FEATURE_SET_VERSION = "v1"
"""Pinned on every version. A feature-formula change is a new feature-set version, which is a
new agent version — otherwise a backtest and a live run would compute different inputs from the
same configuration."""

#: Deterministic namespace so the default prompt maps to one stable prompt_version_id rather
#: than a fresh identifier per version row.
_PROMPT_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def _default_prompt_version_id() -> str:
    name = f"default:{DEFAULT_PROMPT_VERSION}"
    return f"pv_{uuid.uuid5(_PROMPT_NAMESPACE, name).hex}"


class AgentNotFound(Exception):
    """No agent with that id in this workspace."""


class AgentNameTaken(Exception):
    """An agent with that name already exists in this workspace."""


class AgentArchived(Exception):
    """The agent is archived and cannot receive new versions."""


class AgentService:
    def __init__(
        self,
        agents: AgentRepository,
        audit: AuditRepository,
        *,
        workspace_id: str,
        actor: str,
        request_id: str | None = None,
    ) -> None:
        self._agents = agents
        self._audit = audit
        self._workspace_id = workspace_id
        self._actor = actor
        self._request_id = request_id

    async def create_agent(
        self,
        *,
        name: str,
        description: str,
        spec: AgentSpec,
        change_summary: str,
        author_kind: AuthorKind,
    ) -> tuple[Agent, AgentVersionRow]:
        """Create an agent together with version 1.

        An agent without a version would be a configuration that cannot run, so both are written
        in one transaction.
        """
        if await self._agents.get_agent_by_name(name) is not None:
            raise AgentNameTaken(name)

        agent = await self._agents.create_agent(
            name=name, description=description, created_by=self._actor
        )
        version = await self._write_version(
            agent_id=agent.agent_id,
            version_number=1,
            spec=spec,
            change_summary=change_summary,
            author_kind=author_kind,
        )
        await self._audit.record(
            action="agent_version_created",
            actor=self._actor,
            subject_type="agent",
            subject_id=agent.agent_id,
            reason=change_summary,
            request_id=self._request_id,
            payload={
                "version": 1,
                "spec_hash": version.spec_hash,
                "author_kind": author_kind.value,
            },
        )
        return agent, version

    async def create_version(
        self,
        *,
        agent_id: str,
        spec: AgentSpec,
        change_summary: str,
        author_kind: AuthorKind,
    ) -> AgentVersionRow:
        """Append a new immutable version.

        The agent row is locked first so two concurrent edits serialise rather than racing for
        the same version number.
        """
        agent = await self._agents.lock_agent(agent_id)
        if agent is None:
            raise AgentNotFound(agent_id)
        if agent.archived_at is not None:
            raise AgentArchived(agent_id)

        version = await self._write_version(
            agent_id=agent_id,
            version_number=agent.current_version + 1,
            spec=spec,
            change_summary=change_summary,
            author_kind=author_kind,
        )
        await self._audit.record(
            action="agent_version_created",
            actor=self._actor,
            subject_type="agent",
            subject_id=agent_id,
            reason=change_summary,
            request_id=self._request_id,
            payload={
                "version": version.version,
                "spec_hash": version.spec_hash,
                "previous_version": agent.current_version,
                "author_kind": author_kind.value,
            },
        )
        return version

    async def archive_agent(self, agent_id: str, *, reason: str) -> None:
        """Archive an agent. Its versions and decisions remain readable.

        Deleting would destroy the explanation of every decision the agent made, which is the
        opposite of what an audit trail is for.
        """
        archived = await self._agents.archive_agent(agent_id)
        if not archived:
            raise AgentNotFound(agent_id)
        await self._audit.record(
            action="agent_archived",
            actor=self._actor,
            subject_type="agent",
            subject_id=agent_id,
            reason=reason,
            request_id=self._request_id,
        )

    async def _write_version(
        self,
        *,
        agent_id: str,
        version_number: int,
        spec: AgentSpec,
        change_summary: str,
        author_kind: AuthorKind,
    ) -> AgentVersionRow:
        spec_payload: dict[str, Any] = spec.model_dump(mode="json")
        row = await self._agents.insert_version(
            agent_id=agent_id,
            version=version_number,
            spec=spec_payload,
            # Hashed from the validated model, not the serialised payload, so the hash is stable
            # across JSON encoding changes.
            spec_hash=content_hash(spec),
            prompt_version_id=_default_prompt_version_id(),
            prompt_hash=default_prompt_hash(),
            feature_set_version=DEFAULT_FEATURE_SET_VERSION,
            created_by=self._actor,
            author_kind=author_kind.value,
            change_summary=change_summary,
        )
        await self._agents.set_current_version(agent_id, version_number)
        return row
