"""Workspace and membership endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import IntegrityError

from kavrigo_api.auth.dependencies import CurrentPrincipal, WorkspaceDep, get_database
from kavrigo_api.auth.principal import ROLE_PERMISSIONS, Permission, Role
from kavrigo_api.db.session import Database
from kavrigo_api.errors import ApiError, ErrorCode
from kavrigo_api.repositories.identity import IdentityRepository
from kavrigo_api.schemas.workspaces import (
    MeResponse,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceSummary,
)

router = APIRouter(prefix="/v1", tags=["workspaces"])

DatabaseDep = Annotated[Database, Depends(get_database)]


@router.get("/me", response_model=MeResponse, summary="The calling user and their workspaces")
async def me(principal: CurrentPrincipal, database: DatabaseDep) -> MeResponse:
    async with database.global_session(user_id=principal.user_id) as session:
        memberships = await IdentityRepository(session).list_memberships(principal.user_id)

    return MeResponse(
        user_id=principal.user_id,
        email=principal.email,
        mfa_verified=principal.mfa_verified,
        workspaces=[
            WorkspaceSummary(workspace_id=m.workspace_id, name=m.name, slug=m.slug, role=m.role)
            for m in memberships
        ],
        # Advisory only: the client uses this to hide actions it cannot perform. Every request
        # is authorized again server-side.
        permissions={m.workspace_id: sorted(ROLE_PERMISSIONS[m.role]) for m in memberships},
    )


@router.post(
    "/workspaces",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a workspace",
)
async def create_workspace(
    body: WorkspaceCreate,
    principal: CurrentPrincipal,
    database: DatabaseDep,
) -> WorkspaceResponse:
    """Create a workspace with the caller as its owner.

    Not idempotency-keyed: idempotency records are themselves tenant-scoped, and there is no
    tenant yet. The unique slug constraint is what makes a retry safe here.
    """
    async with database.global_session() as session:
        repo = IdentityRepository(session)
        try:
            workspace = await repo.create_workspace(
                name=body.name, slug=body.slug, owner_user_id=principal.user_id
            )
        except IntegrityError as exc:
            raise ApiError(
                ErrorCode.CONFLICT,
                "That workspace slug is already taken.",
                http_status=409,
                details={"slug": body.slug},
            ) from exc
        except ValueError as exc:
            raise ApiError(ErrorCode.VALIDATION_FAILED, str(exc), http_status=400) from exc

        return WorkspaceResponse(
            workspace_id=workspace.workspace_id,
            name=workspace.name,
            slug=workspace.slug,
            created_at=workspace.created_at,
            role=Role.OWNER,
        )


@router.get(
    "/workspaces",
    response_model=list[WorkspaceSummary],
    summary="List the caller's workspaces",
)
async def list_workspaces(
    principal: CurrentPrincipal, database: DatabaseDep
) -> list[WorkspaceSummary]:
    async with database.global_session(user_id=principal.user_id) as session:
        memberships = await IdentityRepository(session).list_memberships(principal.user_id)
    return [
        WorkspaceSummary(workspace_id=m.workspace_id, name=m.name, slug=m.slug, role=m.role)
        for m in memberships
    ]


@router.get(
    "/workspaces/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="Get one workspace",
)
async def get_workspace(context: WorkspaceDep, database: DatabaseDep) -> WorkspaceResponse:
    """Read a workspace the caller belongs to.

    Membership is already proven by resolving the context; a non-member never reaches this body.
    """
    if not context.has(Permission.WORKSPACE_READ):  # pragma: no cover - every role has it
        raise ApiError(ErrorCode.FORBIDDEN, "Not permitted.", http_status=403)

    async with database.global_session(user_id=context.user_id) as session:
        memberships = await IdentityRepository(session).list_memberships(context.user_id)
    for m in memberships:
        if m.workspace_id == context.workspace_id:
            return WorkspaceResponse(
                workspace_id=m.workspace_id,
                name=m.name,
                slug=m.slug,
                created_at=m.created_at,
                role=m.role,
            )
    raise ApiError(ErrorCode.NOT_FOUND, "Workspace not found.", http_status=404)
