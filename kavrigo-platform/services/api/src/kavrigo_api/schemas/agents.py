"""Agent and agent-version schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from kavrigo_domain import AgentSpec, ApprovalStatus, AuthorKind, PromotionStage

__all__ = [
    "AgentCreate",
    "AgentResponse",
    "AgentVersionCreate",
    "AgentVersionResponse",
    "AgentVersionSummary",
]


class AgentCreate(BaseModel):
    """Create an agent and its first version.

    The spec is validated as a full :class:`kavrigo_domain.AgentSpec` before anything is
    written, so an invalid configuration never reaches the database or a run.
    """

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")]
    description: Annotated[str, Field(default="", max_length=1000)] = ""
    spec: AgentSpec
    change_summary: Annotated[str, Field(default="Initial version.", max_length=2000)] = (
        "Initial version."
    )
    author_kind: AuthorKind = AuthorKind.HUMAN


class AgentVersionCreate(BaseModel):
    """Create a new version of an existing agent.

    There is no update endpoint by design: editing an agent creates a version, it does not mutate
    the configuration that produced historical decisions (``MASTER_BUILD_SPEC.md`` §3, §38).
    """

    model_config = ConfigDict(extra="forbid")

    spec: AgentSpec
    change_summary: Annotated[str, Field(min_length=1, max_length=2000)]
    author_kind: AuthorKind = AuthorKind.HUMAN


class AgentVersionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_version_id: str
    agent_id: str
    version: int
    spec_hash: str
    prompt_hash: str
    feature_set_version: str
    stage: PromotionStage
    approval_status: ApprovalStatus
    approved_environments: list[str]
    author_kind: AuthorKind
    change_summary: str
    created_at: datetime
    created_by: str


class AgentVersionResponse(AgentVersionSummary):
    """A version with its full specification."""

    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any]


class AgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    workspace_id: str
    name: str
    description: str
    current_version: int
    created_at: datetime
    created_by: str
    archived_at: datetime | None = None
