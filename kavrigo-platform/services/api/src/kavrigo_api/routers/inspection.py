"""Workspace-scoped, read-only projections of durable engine receipts (ADR 0028)."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import TypeAdapter
from sqlalchemy import text

from kavrigo_api.auth.dependencies import WorkspaceDep, WorkspaceSession, require
from kavrigo_api.auth.principal import Permission
from kavrigo_api.errors import ApiError, ErrorCode
from kavrigo_api.repositories.agents import decode_cursor, encode_cursor
from kavrigo_api.schemas.common import Page
from kavrigo_api.schemas.inspection import (
    AuditSummary,
    PaperAccountView,
    RunInspection,
    RunSummary,
    StageSummary,
)
from kavrigo_domain import AgentDecision, EvidenceItem, content_hash

router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["inspection"])
Limit = Annotated[int, Query(ge=1, le=50)]
Cursor = Annotated[str | None, Query(max_length=512)]
RunPath = Annotated[str, Path(pattern=r"^run_[0-9a-f]{32}$")]


def after(cursor: str | None) -> str:
    if cursor is None:
        return ""
    value = decode_cursor(cursor)
    if value is None or len(value) > 128:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Invalid cursor.")
    return value


def page[T](items: list[T], limit: int, key: str) -> Page[T]:
    more = len(items) > limit
    visible = items[:limit]
    return Page[T](
        items=visible,
        has_more=more,
        next_cursor=encode_cursor(getattr(visible[-1], key)) if more else None,
    )


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


@router.get(
    "/runs", response_model=Page[RunSummary], dependencies=[Depends(require(Permission.RUN_READ))]
)
async def runs(
    context: WorkspaceDep,
    session: WorkspaceSession,
    response: Response,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> Page[RunSummary]:
    no_store(response)
    rows = (
        await session.execute(
            text("""SELECT run_id, definition::jsonb->'job'->>'kind' AS kind,
        CASE WHEN (definition::jsonb #> '{job,evaluation,snapshot,quality,notes}')
          ? 'synthetic_rehearsal_only' THEN 'synthetic_rehearsal' ELSE 'recorded'
        END AS input_kind, status, input_hash, created_at FROM kavrigo.engine_runs
        WHERE workspace_id=:ws AND run_id>:after ORDER BY run_id LIMIT :limit"""),
            {"ws": context.workspace_id, "after": after(cursor), "limit": limit + 1},
        )
    ).mappings()
    return page([RunSummary.model_validate(dict(r)) for r in rows], limit, "run_id")


@router.get(
    "/runs/{run_id}",
    response_model=RunInspection,
    dependencies=[Depends(require(Permission.RUN_READ))],
)
async def run_detail(
    run_id: RunPath,
    context: WorkspaceDep,
    session: WorkspaceSession,
    response: Response,
) -> RunInspection:
    no_store(response)
    params = {"ws": context.workspace_id, "run": run_id}
    found = (
        (
            await session.execute(
                text("""SELECT run_id, definition, status, input_hash, created_at
        FROM kavrigo.engine_runs WHERE workspace_id=:ws AND run_id=:run"""),
                params,
            )
        )
        .mappings()
        .first()
    )
    if found is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Run not found.", 404)
    definition = json.loads(found["definition"])
    if definition["workspace_id"] != context.workspace_id:
        raise ApiError(ErrorCode.INTERNAL_ERROR, "Run scope is inconsistent.", 500)
    rows = (
        (
            await session.execute(
                text("""SELECT stage,status,output,output_hash,started_at,finished_at
        FROM kavrigo.engine_steps WHERE workspace_id=:ws AND run_id=:run ORDER BY started_at,stage"""),
                params,
            )
        )
        .mappings()
        .all()
    )
    stages = []
    decisions: list[AgentDecision] = []
    reasons: list[str] = []
    for row in rows:
        stages.append(StageSummary.model_validate({k: row[k] for k in StageSummary.model_fields}))
        if row["output"] is not None:
            output: dict[str, Any] = json.loads(row["output"])
            if content_hash(output) != row["output_hash"]:
                raise ApiError(ErrorCode.INTERNAL_ERROR, "Run receipt is inconsistent.", 500)
            if row["stage"] == "evaluate":
                decisions = TypeAdapter(list[AgentDecision]).validate_python(
                    output.get("decisions", [])
                )
                if any(d.workspace_id != context.workspace_id for d in decisions):
                    raise ApiError(ErrorCode.INTERNAL_ERROR, "Decision scope is inconsistent.", 500)
                reasons = TypeAdapter(list[str]).validate_python(output.get("reason_codes", []))
                if isinstance(output.get("reason"), str):
                    reasons.append(output["reason"])
    evidence = TypeAdapter(list[EvidenceItem]).validate_python(
        definition["job"].get("evaluation", {}).get("evidence", [])
    )
    notes = (
        definition["job"]
        .get("evaluation", {})
        .get("snapshot", {})
        .get("quality", {})
        .get("notes", [])
    )
    return RunInspection(
        run_id=run_id,
        kind=definition["job"]["kind"],
        input_kind=("synthetic_rehearsal" if "synthetic_rehearsal_only" in notes else "recorded"),
        status=found["status"],
        input_hash=found["input_hash"],
        created_at=found["created_at"],
        stages=stages,
        decisions=decisions,
        evidence=evidence,
        reason_codes=reasons,
    )


@router.get(
    "/paper/accounts",
    response_model=Page[PaperAccountView],
    dependencies=[Depends(require(Permission.RUN_READ))],
)
async def accounts(
    context: WorkspaceDep,
    session: WorkspaceSession,
    response: Response,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> Page[PaperAccountView]:
    no_store(response)
    rows = (
        await session.execute(
            text("""SELECT account_id,head_sequence,head_hash,head_receipt
        FROM kavrigo.engine_accounts WHERE workspace_id=:ws AND account_id>:after
        ORDER BY account_id LIMIT :limit"""),
            {"ws": context.workspace_id, "after": after(cursor), "limit": limit + 1},
        )
    ).mappings()
    result = []
    for row in rows:
        receipt = json.loads(row["head_receipt"])
        state = receipt["state"]
        if (
            receipt["sequence"] != row["head_sequence"]
            or receipt["state_hash"] != row["head_hash"]
            or state["account_id"] != row["account_id"]
            or state["portfolio"]["workspace_id"] != context.workspace_id
            or state["portfolio"]["mode"] != "paper"
        ):
            raise ApiError(ErrorCode.INTERNAL_ERROR, "Paper receipt is inconsistent.", 500)
        result.append(
            PaperAccountView(
                account_id=row["account_id"],
                sequence=receipt["sequence"],
                state_hash=receipt["state_hash"],
                committed_at=receipt["committed_at"],
                portfolio=state["portfolio"],
                fees_paid=state["fees_paid"],
            )
        )
    return page(result, limit, "account_id")


@router.get(
    "/audit",
    response_model=Page[AuditSummary],
    dependencies=[Depends(require(Permission.AUDIT_READ))],
)
async def audit(
    context: WorkspaceDep,
    session: WorkspaceSession,
    response: Response,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> Page[AuditSummary]:
    no_store(response)
    rows = (
        await session.execute(
            text("""SELECT audit_id AS event_id,action,
        coalesce(subject_type,'workspace') AS resource_type,coalesce(subject_id,workspace_id) AS resource_id,
        created_at AS occurred_at FROM kavrigo.audit_events WHERE workspace_id=:ws AND audit_id>:after
        ORDER BY audit_id LIMIT :limit"""),
            {"ws": context.workspace_id, "after": after(cursor), "limit": limit + 1},
        )
    ).mappings()
    return page([AuditSummary.model_validate(dict(r)) for r in rows], limit, "event_id")
