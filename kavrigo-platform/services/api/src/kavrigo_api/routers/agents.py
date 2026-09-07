"""Agent endpoints.

Note what is *absent*: there is no ``PATCH /agents/{id}`` that changes behaviour. Editing an
agent means creating a version (``MASTER_BUILD_SPEC.md`` §3, §38), so the only route that
changes what an agent does is ``POST .../versions``. Historical decisions stay explicable
because the configuration that produced them is never rewritten.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError

from kavrigo_api.auth.dependencies import WorkspaceDep, WorkspaceSession, require
from kavrigo_api.auth.principal import Permission, WorkspaceContext
from kavrigo_api.db.models import Agent, AgentVersionRow
from kavrigo_api.errors import ApiError, ErrorCode
from kavrigo_api.repositories.agents import AgentRepository, decode_cursor, encode_cursor
from kavrigo_api.repositories.audit import AuditRepository
from kavrigo_api.repositories.idempotency import IdempotencyRepository
from kavrigo_api.schemas.agents import (
    AgentCreate,
    AgentResponse,
    AgentVersionCreate,
    AgentVersionResponse,
    AgentVersionSummary,
)
from kavrigo_api.schemas.common import Page
from kavrigo_api.services.agents import (
    AgentArchived,
    AgentNameTaken,
    AgentNotFound,
    AgentService,
)
from kavrigo_api.services.idempotency import (
    idempotency_key_from,
    replay_or_none,
    request_fingerprint,
    store_result,
)
from kavrigo_domain import ApprovalStatus, AuthorKind, PromotionStage

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/agents", tags=["agents"])

AgentIdPath = Annotated[str, Path(pattern=r"^ag_[0-9a-f]{32}$")]


def _agent_response(agent: Agent) -> AgentResponse:
    return AgentResponse(
        agent_id=agent.agent_id,
        workspace_id=agent.workspace_id,
        name=agent.name,
        description=agent.description,
        current_version=agent.current_version,
        created_at=agent.created_at,
        created_by=agent.created_by,
        archived_at=agent.archived_at,
    )


def _version_summary(row: AgentVersionRow) -> AgentVersionSummary:
    return AgentVersionSummary(
        agent_version_id=row.agent_version_id,
        agent_id=row.agent_id,
        version=row.version,
        spec_hash=row.spec_hash,
        prompt_hash=row.prompt_hash,
        feature_set_version=row.feature_set_version,
        stage=PromotionStage(row.stage),
        approval_status=ApprovalStatus(row.approval_status),
        approved_environments=list(row.approved_environments),
        author_kind=AuthorKind(row.author_kind),
        change_summary=row.change_summary,
        created_at=row.created_at,
        created_by=row.created_by,
    )


def _version_response(row: AgentVersionRow) -> AgentVersionResponse:
    return AgentVersionResponse(**_version_summary(row).model_dump(), spec=row.spec)


def _service(session: WorkspaceSession, context: WorkspaceDep, request: Request) -> AgentService:
    return AgentService(
        AgentRepository(session, context.workspace_id),
        AuditRepository(session, context.workspace_id),
        workspace_id=context.workspace_id,
        actor=context.user_id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("", response_model=Page[AgentResponse], summary="List agents")
async def list_agents(
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.AGENT_READ))],
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    include_archived: Annotated[bool, Query()] = False,
) -> Page[AgentResponse]:
    after = decode_cursor(cursor) if cursor else None
    if cursor and after is None:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Invalid cursor.", http_status=400)

    repo = AgentRepository(session, context.workspace_id)
    # Fetch one extra row to determine `has_more` without a second count query.
    rows = await repo.list_agents(
        limit=limit + 1, after_agent_id=after, include_archived=include_archived
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return Page[AgentResponse](
        items=[_agent_response(a) for a in rows],
        next_cursor=encode_cursor(rows[-1].agent_id) if has_more and rows else None,
        has_more=has_more,
    )


@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an agent and its first version",
)
async def create_agent(
    body: AgentCreate,
    request: Request,
    response: Response,
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.AGENT_CREATE))],
) -> AgentResponse:
    workspace_id = context.workspace_id

    key = idempotency_key_from(request)
    fingerprint = request_fingerprint(body)
    idem = IdempotencyRepository(session, workspace_id)
    replayed = await replay_or_none(idem, key=key, endpoint="POST /agents", fingerprint=fingerprint)
    if replayed is not None:
        response.status_code = replayed.status
        return AgentResponse.model_validate(replayed.body)

    service = _service(session, context, request)
    try:
        agent, _version = await service.create_agent(
            name=body.name,
            description=body.description,
            spec=body.spec,
            change_summary=body.change_summary,
            author_kind=body.author_kind,
        )
    except AgentNameTaken as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "An agent with that name already exists in this workspace.",
            http_status=409,
            details={"name": body.name},
        ) from exc
    except IntegrityError as exc:
        raise ApiError(
            ErrorCode.CONFLICT, "The agent could not be created.", http_status=409
        ) from exc

    payload = _agent_response(agent)
    await store_result(
        idem,
        key=key,
        endpoint="POST /agents",
        fingerprint=fingerprint,
        status=status.HTTP_201_CREATED,
        body=payload.model_dump(mode="json"),
    )
    return payload


@router.get("/{agent_id}", response_model=AgentResponse, summary="Get an agent")
async def get_agent(
    agent_id: AgentIdPath,
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.AGENT_READ))],
) -> AgentResponse:
    repo = AgentRepository(session, context.workspace_id)
    agent = await repo.get_agent(agent_id)
    if agent is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Agent not found.", http_status=404)
    return _agent_response(agent)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive an agent",
)
async def archive_agent(
    agent_id: AgentIdPath,
    request: Request,
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.AGENT_ARCHIVE))],
    reason: Annotated[str, Query(max_length=500)] = "",
) -> Response:
    """Archive, never delete: the agent's versions explain its historical decisions."""
    service = _service(session, context, request)
    try:
        await service.archive_agent(agent_id, reason=reason)
    except AgentNotFound as exc:
        raise ApiError(ErrorCode.NOT_FOUND, "Agent not found.", http_status=404) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{agent_id}/versions",
    response_model=Page[AgentVersionSummary],
    summary="List agent versions, newest first",
)
async def list_versions(
    agent_id: AgentIdPath,
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.AGENT_READ))],
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[AgentVersionSummary]:
    repo = AgentRepository(session, context.workspace_id)
    if await repo.get_agent(agent_id) is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Agent not found.", http_status=404)

    before: int | None = None
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded is None or not decoded.isdigit():
            raise ApiError(ErrorCode.VALIDATION_FAILED, "Invalid cursor.", http_status=400)
        before = int(decoded)

    rows = await repo.list_versions(agent_id, limit=limit + 1, before_version=before)
    has_more = len(rows) > limit
    rows = rows[:limit]
    return Page[AgentVersionSummary](
        items=[_version_summary(r) for r in rows],
        next_cursor=encode_cursor(str(rows[-1].version)) if has_more and rows else None,
        has_more=has_more,
    )


@router.post(
    "/{agent_id}/versions",
    response_model=AgentVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new immutable version",
)
async def create_version(
    agent_id: AgentIdPath,
    body: AgentVersionCreate,
    request: Request,
    response: Response,
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.AGENT_UPDATE))],
) -> AgentVersionResponse:
    """Append a version. The previous version is untouched and remains readable."""
    workspace_id = context.workspace_id
    key = idempotency_key_from(request)
    fingerprint = request_fingerprint(body)
    idem = IdempotencyRepository(session, workspace_id)
    endpoint = f"POST /agents/{agent_id}/versions"
    replayed = await replay_or_none(idem, key=key, endpoint=endpoint, fingerprint=fingerprint)
    if replayed is not None:
        response.status_code = replayed.status
        return AgentVersionResponse.model_validate(replayed.body)

    service = _service(session, context, request)
    try:
        row = await service.create_version(
            agent_id=agent_id,
            spec=body.spec,
            change_summary=body.change_summary,
            author_kind=body.author_kind,
        )
    except AgentNotFound as exc:
        raise ApiError(ErrorCode.NOT_FOUND, "Agent not found.", http_status=404) from exc
    except AgentArchived as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "This agent is archived and cannot receive new versions.",
            http_status=409,
        ) from exc

    payload = _version_response(row)
    await store_result(
        idem,
        key=key,
        endpoint=endpoint,
        fingerprint=fingerprint,
        status=status.HTTP_201_CREATED,
        body=payload.model_dump(mode="json"),
    )
    return payload


@router.get(
    "/{agent_id}/versions/{version}",
    response_model=AgentVersionResponse,
    summary="Get one version with its full specification",
)
async def get_version(
    agent_id: AgentIdPath,
    version: Annotated[int, Path(ge=1)],
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.AGENT_READ))],
) -> AgentVersionResponse:
    repo = AgentRepository(session, context.workspace_id)
    row = await repo.get_version(agent_id, version)
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Agent version not found.", http_status=404)
    return _version_response(row)
