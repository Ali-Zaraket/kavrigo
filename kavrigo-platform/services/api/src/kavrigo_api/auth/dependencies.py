"""FastAPI dependencies for authentication and tenant authorization.

The chain is always the same, and each step is a separate check:

```text
bearer token  → IdentityProvider.verify   (is this a valid session?)
              → local user upsert          (who is this, in our terms?)
              → membership lookup          (do they belong to this workspace?)
              → permission check           (may they do this, and is MFA satisfied?)
              → RLS-scoped session         (can the database even see other rows?)
```

The workspace comes from the URL path, and is then validated against a stored membership. A
client-supplied identifier never grants access on its own (``MASTER_BUILD_SPEC.md`` §20).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from kavrigo_api.auth.identity import IdentityProvider, IdentityVerificationError
from kavrigo_api.auth.principal import Permission, Principal, WorkspaceContext
from kavrigo_api.db.session import Database
from kavrigo_api.errors import ApiError, ErrorCode
from kavrigo_api.logging import get_logger
from kavrigo_api.repositories.identity import IdentityRepository

__all__ = [
    "CurrentPrincipal",
    "WorkspaceDep",
    "WorkspaceSession",
    "get_database",
    "get_identity_provider",
    "require",
    "workspace_session",
]

_log = get_logger(__name__)

#: ``auto_error=False`` so a missing header produces our structured error body rather than
#: FastAPI's default shape.
_bearer = HTTPBearer(auto_error=False, description="Identity provider session token")


def get_database(request: Request) -> Database:
    database: Database | None = getattr(request.app.state, "database", None)
    if database is None:
        raise ApiError(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            "The control-plane database is not configured.",
            http_status=503,
        )
    return database


def get_identity_provider(request: Request) -> IdentityProvider:
    provider: IdentityProvider | None = getattr(request.app.state, "identity_provider", None)
    if provider is None:
        raise ApiError(
            ErrorCode.UPSTREAM_UNAVAILABLE,
            "Authentication is not configured.",
            http_status=503,
        )
    return provider


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    provider: Annotated[IdentityProvider, Depends(get_identity_provider)],
    database: Annotated[Database, Depends(get_database)],
) -> Principal:
    """Verify the bearer token and resolve it to a local user."""
    if credentials is None or not credentials.credentials:
        raise ApiError(
            ErrorCode.UNAUTHENTICATED,
            "A bearer token is required.",
            http_status=401,
        )

    try:
        identity = await provider.verify(credentials.credentials)
    except IdentityVerificationError as exc:
        # The specific reason is logged; the client is told only that it failed.
        _log.info("authentication_failed", request_id=getattr(request.state, "request_id", None))
        raise ApiError(
            ErrorCode.UNAUTHENTICATED,
            "The session token is invalid or expired.",
            http_status=401,
        ) from exc

    async with database.global_session() as session:
        user = await IdentityRepository(session).ensure_user(
            external_id=identity.subject, email=identity.email
        )
        user_id = user.user_id

    return Principal(
        user_id=user_id,
        external_id=identity.subject,
        email=identity.email,
        mfa_verified=identity.mfa_verified,
        session_id=identity.session_id,
    )


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


async def workspace_context(
    principal: CurrentPrincipal,
    database: Annotated[Database, Depends(get_database)],
    workspace_id: Annotated[str, Path(pattern=r"^ws_[0-9a-f]{32}$")],
) -> WorkspaceContext:
    """Resolve the caller's role in the workspace named in the path.

    A non-member gets ``404``, not ``403``: confirming that a workspace exists to someone with
    no standing in it leaks its existence and lets an attacker enumerate tenants.
    """
    async with database.global_session(user_id=principal.user_id) as session:
        role = await IdentityRepository(session).get_role(
            workspace_id=workspace_id, user_id=principal.user_id
        )
    if role is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Workspace not found.",
            http_status=404,
        )
    return WorkspaceContext(principal=principal, workspace_id=workspace_id, role=role)


WorkspaceDep = Annotated[WorkspaceContext, Depends(workspace_context)]


def require(permission: Permission) -> Callable[[WorkspaceContext], Awaitable[WorkspaceContext]]:
    """Dependency factory enforcing one permission.

    Separates "your role cannot do this" from "your role can, but this session has no verified
    second factor" so the client can prompt for re-authentication instead of showing a dead end.
    """

    async def _dependency(context: WorkspaceDep) -> WorkspaceContext:
        if context.has(permission):
            return context
        if context.missing_mfa_for(permission):
            raise ApiError(
                ErrorCode.FORBIDDEN,
                "This action requires multi-factor authentication.",
                http_status=403,
                details={"permission": permission.value, "reason": "mfa_required"},
            )
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Your role does not permit this action.",
            http_status=403,
            details={"permission": permission.value, "role": context.role.value},
        )

    return _dependency


async def workspace_session(
    context: WorkspaceDep,
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    """An RLS-scoped transaction for the resolved workspace."""
    async with database.workspace_session(context.workspace_id) as session:
        yield session


WorkspaceSession = Annotated[AsyncSession, Depends(workspace_session)]
