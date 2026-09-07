"""Workspace and membership schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from kavrigo_api.auth.principal import Permission, Role

__all__ = [
    "MeResponse",
    "MembershipResponse",
    "WorkspaceCreate",
    "WorkspaceResponse",
    "WorkspaceSummary",
]


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=120)]
    slug: Annotated[
        str, Field(min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    ]


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    name: str
    slug: str
    created_at: datetime
    role: Role
    """The calling user's role in this workspace."""


class WorkspaceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    name: str
    slug: str
    role: Role


class MembershipResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    user_id: str
    role: Role
    created_at: datetime


class MeResponse(BaseModel):
    """Who the caller is, and what they can reach.

    ``permissions`` is returned per workspace so the client can hide actions it cannot perform.
    The server re-checks every one of them — a hidden button is a usability feature, never a
    security control.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: str
    email: str | None
    mfa_verified: bool
    workspaces: list[WorkspaceSummary]
    permissions: dict[str, list[Permission]]
