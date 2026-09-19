"""Workspace-scoped, MFA-gated policy candidates; no approval or activation route."""

import re
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Path, Query, Request, status
from sqlalchemy import text

from kavrigo_api.auth.dependencies import WorkspaceSession, require
from kavrigo_api.auth.principal import Permission, WorkspaceContext
from kavrigo_api.db.models import PaperPolicyBundle
from kavrigo_api.errors import ApiError, ErrorCode
from kavrigo_api.logging import get_logger
from kavrigo_api.repositories.agents import decode_cursor, encode_cursor
from kavrigo_api.repositories.audit import AuditRepository
from kavrigo_api.repositories.paper_policies import PaperPolicyRepository
from kavrigo_api.schemas.common import Page
from kavrigo_api.schemas.paper_policies import PaperPolicyBundleCreate, PaperPolicyBundleResponse
from kavrigo_api.services.idempotency import idempotency_key_from, request_fingerprint
from kavrigo_domain import RiskPolicy, RiskScope, content_hash
from kavrigo_risk import RiskExecutionPolicy, policy_hash

router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/paper/policy-bundles", tags=["paper-policies"]
)
_log = get_logger(__name__)
_NAMESPACE = UUID("a50c23a7-97a7-4723-b338-2382776b62b4")
BundlePath = Annotated[str, Path(pattern=r"^pb_[0-9a-f]{32}$")]


def _response(row: PaperPolicyBundle) -> PaperPolicyBundleResponse:
    risk = RiskPolicy.model_validate(row.risk_document)
    execution = RiskExecutionPolicy.model_validate(row.execution_document)
    if (
        risk.workspace_id != row.workspace_id
        or risk.scope is not RiskScope.AGENT
        or risk.risk_policy_id != row.risk_policy_id
        or policy_hash(risk) != row.risk_hash
        or risk.content_hash != row.risk_hash
        or execution.execution_policy_id != row.execution_policy_id
        or content_hash(execution) != row.execution_hash
    ):
        raise ApiError(ErrorCode.CONFLICT, "Stored policy integrity check failed.", 409)
    return PaperPolicyBundleResponse(
        bundle_id=row.bundle_id,
        workspace_id=row.workspace_id,
        risk=risk,
        execution=execution,
        risk_hash=row.risk_hash,
        execution_hash=row.execution_hash,
        reason=row.reason,
        created_by=row.created_by,
        created_at=row.created_at,
    )


@router.post(
    "",
    response_model=PaperPolicyBundleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Store an immutable, unapproved paper-policy candidate pair",
)
async def create_paper_policy_bundle(
    body: PaperPolicyBundleCreate,
    request: Request,
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.RISK_POLICY_WRITE))],
) -> PaperPolicyBundleResponse:
    key = idempotency_key_from(request)
    if key is None or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key) is None:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "A valid Idempotency-Key is required.", 400)
    bundle_id = "pb_" + uuid5(_NAMESPACE, context.workspace_id + ":" + key).hex
    fingerprint = request_fingerprint(body)
    # Serialize same-key callers before checking the row; the bundle and audit commit together.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:bundle, 0))"),
        {"bundle": bundle_id},
    )
    repo = PaperPolicyRepository(session, context.workspace_id)
    existing = await repo.get(bundle_id)
    if existing is not None:
        if existing.request_hash != fingerprint:
            raise ApiError(
                ErrorCode.IDEMPOTENCY_KEY_REUSED,
                "This Idempotency-Key belongs to another policy candidate.",
                409,
            )
        return _response(existing)

    at = datetime.now(UTC)
    risk_id = "rp_" + uuid5(_NAMESPACE, bundle_id + ":risk").hex
    execution_id = "ep_" + uuid5(_NAMESPACE, bundle_id + ":execution").hex
    risk = RiskPolicy(
        risk_policy_id=risk_id,
        workspace_id=context.workspace_id,
        version=1,
        scope=RiskScope.AGENT,
        limits=body.limits,
        freshness=body.freshness,
        event_risk=body.event_risk,
        created_at=at,
        created_by=context.user_id,
        content_hash="sha256:" + "0" * 64,
    )
    risk = RiskPolicy.model_validate({**risk.model_dump(), "content_hash": policy_hash(risk)})
    execution = RiskExecutionPolicy(
        execution_policy_id=execution_id,
        version="paper-candidate-v1",
        **body.execution.model_dump(),
    )
    row = PaperPolicyBundle(
        bundle_id=bundle_id,
        workspace_id=context.workspace_id,
        risk_policy_id=risk_id,
        execution_policy_id=execution_id,
        risk_document=risk.model_dump(mode="json"),
        risk_hash=risk.content_hash,
        execution_document=execution.model_dump(mode="json"),
        execution_hash=content_hash(execution),
        request_hash=fingerprint,
        reason=body.reason,
        created_by=context.user_id,
    )
    await repo.insert(row)
    await AuditRepository(session, context.workspace_id).record(
        action="paper_policy_candidate_created",
        actor=context.user_id,
        subject_type="paper_policy_bundle",
        subject_id=bundle_id,
        reason=body.reason,
        request_id=getattr(request.state, "request_id", None),
        payload={"risk_hash": row.risk_hash, "execution_hash": row.execution_hash},
    )
    _log.info("paper_policy_candidate_created")
    return _response(row)


@router.get(
    "", response_model=Page[PaperPolicyBundleResponse], summary="List paper-policy candidates"
)
async def list_paper_policy_bundles(
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.RISK_POLICY_READ))],
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> Page[PaperPolicyBundleResponse]:
    after = decode_cursor(cursor) if cursor else None
    if cursor and (after is None or re.fullmatch(r"pb_[0-9a-f]{32}", after) is None):
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Invalid cursor.", 400)
    rows = await PaperPolicyRepository(session, context.workspace_id).list(
        limit=limit + 1, after=after
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return Page[PaperPolicyBundleResponse](
        items=[_response(row) for row in rows],
        next_cursor=encode_cursor(rows[-1].bundle_id) if has_more and rows else None,
        has_more=has_more,
    )


@router.get(
    "/{bundle_id}",
    response_model=PaperPolicyBundleResponse,
    summary="Read a paper-policy candidate",
)
async def get_paper_policy_bundle(
    bundle_id: BundlePath,
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.RISK_POLICY_READ))],
) -> PaperPolicyBundleResponse:
    row = await PaperPolicyRepository(session, context.workspace_id).get(bundle_id)
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Policy candidate not found.", 404)
    return _response(row)
