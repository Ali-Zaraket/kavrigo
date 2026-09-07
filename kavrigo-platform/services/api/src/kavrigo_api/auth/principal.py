"""Principals, roles and permissions.

The tenant boundary is ``workspace_id`` (``MASTER_BUILD_SPEC.md`` §20). A ``Principal`` is *who*
is calling; a ``WorkspaceContext`` is *who is calling, acting in which workspace, with what
role*. Nothing in the application may act on tenant data holding only a ``Principal`` — the
workspace must be resolved from a verified membership, never from a client-supplied header
alone.

Permissions are an explicit matrix rather than scattered role comparisons, so that "can a viewer
do this?" is answerable by reading one table instead of auditing every endpoint.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Permission",
    "Principal",
    "Role",
    "WorkspaceContext",
]


class Role(StrEnum):
    """Workspace roles, least privileged last.

    ``OWNER`` and ``ADMIN`` are distinguished because deleting a workspace, or removing its last
    owner, should not be available to everyone who can administer agents.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Permission(StrEnum):
    """Discrete capabilities. Add, never repurpose."""

    WORKSPACE_READ = "workspace:read"
    WORKSPACE_UPDATE = "workspace:update"
    WORKSPACE_DELETE = "workspace:delete"
    MEMBER_READ = "member:read"
    MEMBER_INVITE = "member:invite"
    MEMBER_REMOVE = "member:remove"
    AGENT_READ = "agent:read"
    AGENT_CREATE = "agent:create"
    AGENT_UPDATE = "agent:update"
    AGENT_ARCHIVE = "agent:archive"
    AGENT_PROMOTE = "agent:promote"
    RISK_POLICY_READ = "risk_policy:read"
    RISK_POLICY_WRITE = "risk_policy:write"
    RUN_READ = "run:read"
    RUN_START = "run:start"
    RUN_STOP = "run:stop"
    AUDIT_READ = "audit:read"
    EXCHANGE_CONNECTION_READ = "exchange_connection:read"
    EXCHANGE_CONNECTION_WRITE = "exchange_connection:write"


#: Capabilities that additionally require a recently re-verified MFA factor
#: (``MASTER_BUILD_SPEC.md`` §21). Role alone is not sufficient for these.
MFA_REQUIRED_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.EXCHANGE_CONNECTION_WRITE,
        Permission.RISK_POLICY_WRITE,
        Permission.WORKSPACE_DELETE,
        Permission.AGENT_PROMOTE,
    }
)

_VIEWER: frozenset[Permission] = frozenset(
    {
        Permission.WORKSPACE_READ,
        Permission.MEMBER_READ,
        Permission.AGENT_READ,
        Permission.RISK_POLICY_READ,
        Permission.RUN_READ,
        Permission.EXCHANGE_CONNECTION_READ,
    }
)

_MEMBER: frozenset[Permission] = _VIEWER | {
    Permission.AGENT_CREATE,
    Permission.AGENT_UPDATE,
    Permission.AGENT_ARCHIVE,
    Permission.RUN_START,
    Permission.RUN_STOP,
}

_ADMIN: frozenset[Permission] = _MEMBER | {
    Permission.WORKSPACE_UPDATE,
    Permission.MEMBER_INVITE,
    Permission.MEMBER_REMOVE,
    Permission.RISK_POLICY_WRITE,
    Permission.AGENT_PROMOTE,
    Permission.AUDIT_READ,
    Permission.EXCHANGE_CONNECTION_WRITE,
}

_OWNER: frozenset[Permission] = _ADMIN | {Permission.WORKSPACE_DELETE}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: _VIEWER,
    Role.MEMBER: _MEMBER,
    Role.ADMIN: _ADMIN,
    Role.OWNER: _OWNER,
}


class Principal(BaseModel):
    """An authenticated caller, before any workspace is chosen."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: Annotated[str, Field(pattern=r"^usr_[0-9a-f]{32}$")]
    external_id: Annotated[str, Field(min_length=1, max_length=128)]
    """The identity provider's subject claim. Stable for the life of the account."""

    email: Annotated[str | None, Field(default=None, max_length=320)] = None
    mfa_verified: bool = False
    """Whether the session presented a second factor. Required for high-impact operations."""

    session_id: Annotated[str | None, Field(default=None, max_length=128)] = None


class WorkspaceContext(BaseModel):
    """A principal acting inside one workspace, with a role resolved from a stored membership.

    Every tenant-scoped query, object-store prefix and cache key derives from ``workspace_id``
    here. It is set from a verified membership lookup, never from request input.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal: Principal
    workspace_id: Annotated[str, Field(pattern=r"^ws_[0-9a-f]{32}$")]
    role: Role

    @property
    def user_id(self) -> str:
        return self.principal.user_id

    @property
    def permissions(self) -> frozenset[Permission]:
        return ROLE_PERMISSIONS[self.role]

    def has(self, permission: Permission) -> bool:
        """Whether this context may perform ``permission``.

        High-impact permissions additionally require a verified second factor: an attacker with
        a stolen session should not be able to write exchange credentials or relax risk policy
        (``MASTER_BUILD_SPEC.md`` §21).
        """
        if permission not in self.permissions:
            return False
        if permission in MFA_REQUIRED_PERMISSIONS:
            return self.principal.mfa_verified
        return True

    def missing_mfa_for(self, permission: Permission) -> bool:
        """True when the role allows the action but the session lacks a second factor.

        Distinguished from a plain denial so the API can return an actionable error telling the
        user to re-authenticate rather than a bare 403.
        """
        return (
            permission in self.permissions
            and permission in MFA_REQUIRED_PERMISSIONS
            and not self.principal.mfa_verified
        )
