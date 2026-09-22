"""Fail-closed paper-activation eligibility assessments."""

import json
import re
from typing import Annotated, Literal, cast
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Path, Request, status
from pydantic import TypeAdapter
from sqlalchemy import text

from kavrigo_api.auth.dependencies import WorkspaceSession, require
from kavrigo_api.auth.principal import Permission, WorkspaceContext
from kavrigo_api.db.models import PaperActivationAssessment
from kavrigo_api.errors import ApiError, ErrorCode
from kavrigo_api.logging import get_logger
from kavrigo_api.repositories.agents import AgentRepository
from kavrigo_api.repositories.audit import AuditRepository
from kavrigo_api.repositories.paper_activation import PaperActivationRepository
from kavrigo_api.repositories.paper_policies import PaperPolicyRepository
from kavrigo_api.schemas.paper_activation import (
    PaperActivationAssessmentCreate,
    PaperActivationAssessmentResponse,
    PaperActivationGateName,
    PaperActivationGateResult,
)
from kavrigo_api.services.idempotency import idempotency_key_from, request_fingerprint
from kavrigo_api.services.paper_policy_integrity import validate_approval
from kavrigo_domain import AgentSpec, TradingMode, content_hash
from kavrigo_workflows.contracts import AgentJob, RunDefinition

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/agents", tags=["paper-activation"])
_log = get_logger(__name__)
_NAMESPACE = UUID("c02a693b-167c-4b07-9dd3-3b1fc20bd9f7")
AgentPath = Annotated[str, Path(pattern=r"^ag_[0-9a-f]{32}$")]
VersionPath = Annotated[int, Path(ge=1)]
AssessmentPath = Annotated[str, Path(pattern=r"^paa_[0-9a-f]{32}$")]
_gate_adapter = TypeAdapter(list[PaperActivationGateResult])
_GATE_ORDER: tuple[PaperActivationGateName, ...] = (
    "policy_approval_integrity",
    "version_policy_binding",
    "evaluation_completion",
    "evaluation_version_binding",
    "promotable_evidence",
    "provider_entitlement",
    "activation_support",
)


def _response(row: PaperActivationAssessment) -> PaperActivationAssessmentResponse:
    gates = _gate_adapter.validate_python(row.gate_results)
    gate_documents = [gate.model_dump(mode="json") for gate in gates]
    expected_decision = "eligible" if gates and all(gate.passed for gate in gates) else "blocked"
    if (
        tuple(gate.gate for gate in gates) != _GATE_ORDER
        or content_hash(gate_documents) != row.gate_hash
        or row.decision != expected_decision
    ):
        raise ApiError(
            ErrorCode.CONFLICT, "Stored activation assessment integrity check failed.", 409
        )
    return PaperActivationAssessmentResponse(
        assessment_id=row.assessment_id,
        workspace_id=row.workspace_id,
        agent_id=row.agent_id,
        agent_version_id=row.agent_version_id,
        version=row.version,
        bundle_id=row.bundle_id,
        approval_id=row.approval_id,
        evaluation_run_id=row.evaluation_run_id,
        agent_spec_hash=row.agent_spec_hash,
        risk_hash=row.risk_hash,
        execution_hash=row.execution_hash,
        evaluation_input_hash=row.evaluation_input_hash,
        evaluation_output_hash=row.evaluation_output_hash,
        providers=list(row.providers),
        license_refs=list(row.license_refs),
        gate_results=gates,
        decision=cast(Literal["blocked", "eligible"], row.decision),
        reason=row.reason,
        assessed_by=row.assessed_by,
        assessed_at=row.assessed_at,
    )


def _gate(
    gate: PaperActivationGateName, passed: bool, reason_code: str
) -> PaperActivationGateResult:
    return PaperActivationGateResult.model_validate(
        {"gate": gate, "passed": passed, "reason_code": reason_code}
    )


@router.post(
    "/{agent_id}/versions/{version}/paper-activation-assessments",
    response_model=PaperActivationAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a fail-closed paper-activation eligibility assessment",
)
async def assess_paper_activation(
    agent_id: AgentPath,
    version: VersionPath,
    body: PaperActivationAssessmentCreate,
    request: Request,
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.AGENT_PROMOTE))],
) -> PaperActivationAssessmentResponse:
    key = idempotency_key_from(request)
    if key is None or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key) is None:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "A valid Idempotency-Key is required.", 400)
    assessment_id = "paa_" + uuid5(_NAMESPACE, context.workspace_id + ":" + key).hex
    fingerprint = request_fingerprint(body)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:assessment, 0))"),
        {"assessment": assessment_id},
    )
    assessments = PaperActivationRepository(session, context.workspace_id)
    existing = await assessments.get(assessment_id)
    if existing is not None:
        if (
            existing.idempotency_key != key
            or existing.request_hash != fingerprint
            or existing.assessed_by != context.user_id
            or existing.agent_id != agent_id
            or existing.version != version
        ):
            raise ApiError(
                ErrorCode.IDEMPOTENCY_KEY_REUSED,
                "This Idempotency-Key belongs to another activation assessment.",
                409,
            )
        return _response(existing)

    agents = AgentRepository(session, context.workspace_id)
    agent = await agents.get_agent(agent_id)
    version_row = await agents.get_version(agent_id, version)
    if agent is None or version_row is None or agent.archived_at is not None:
        raise ApiError(ErrorCode.NOT_FOUND, "Agent version not found.", 404)
    spec = AgentSpec.model_validate(version_row.spec)
    if (
        content_hash(spec) != version_row.spec_hash
        or body.agent_spec_hash != version_row.spec_hash
        or spec.mode is not TradingMode.PAPER
    ):
        raise ApiError(ErrorCode.CONFLICT, "Agent version integrity check failed.", 409)

    policies = PaperPolicyRepository(session, context.workspace_id)
    bundle = await policies.get(body.bundle_id)
    review = await policies.get_review(body.bundle_id)
    approval = await policies.get_approval(body.bundle_id)
    if bundle is None or review is None or approval is None:
        raise ApiError(ErrorCode.CONFLICT, "An approved paper-policy bundle is required.", 409)
    validate_approval(approval, review, bundle)
    if (
        approval.approval_id != body.approval_id
        or bundle.risk_hash != body.risk_hash
        or bundle.execution_hash != body.execution_hash
    ):
        raise ApiError(
            ErrorCode.CONFLICT, "Approved policy identifiers or hashes do not match.", 409
        )

    found = (
        (
            await session.execute(
                text("""SELECT definition,input_hash,status FROM kavrigo.engine_runs
                WHERE workspace_id=:ws AND run_id=:run"""),
                {"ws": context.workspace_id, "run": body.evaluation_run_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if found is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Evaluation run not found.", 404)
    definition = RunDefinition.model_validate_json(found["definition"])
    if (
        content_hash(definition) != found["input_hash"]
        or body.evaluation_input_hash != found["input_hash"]
        or definition.workspace_id != context.workspace_id
    ):
        raise ApiError(ErrorCode.CONFLICT, "Evaluation run integrity check failed.", 409)

    evaluate = (
        (
            await session.execute(
                text("""SELECT status,output,output_hash FROM kavrigo.engine_steps
                WHERE workspace_id=:ws AND run_id=:run AND stage='evaluate'"""),
                {"ws": context.workspace_id, "run": body.evaluation_run_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    evaluation_output_hash: str | None = None
    if evaluate is not None and evaluate["output"] is not None:
        if content_hash(json.loads(evaluate["output"])) != evaluate["output_hash"]:
            raise ApiError(ErrorCode.CONFLICT, "Evaluation receipt integrity check failed.", 409)
        evaluation_output_hash = evaluate["output_hash"]

    job = definition.job
    is_agent_run = isinstance(job, AgentJob)
    if isinstance(job, AgentJob):
        version_bound = bool(
            job.registration.agent_version.agent_version_id == version_row.agent_version_id
            and job.registration.agent_version.spec_hash == version_row.spec_hash
            and job.evaluation.agent_version_id == version_row.agent_version_id
        )
        evidence = job.evaluation.evidence
        notes = set(job.evaluation.snapshot.quality.notes)
    else:
        version_bound = False
        evidence = ()
        notes = set()
    evaluation_complete = bool(
        is_agent_run
        and found["status"] == "completed"
        and evaluate is not None
        and evaluate["status"] == "completed"
        and evaluation_output_hash is not None
    )
    providers = sorted({item.provider for item in evidence})
    license_refs = sorted({item.license_ref for item in evidence if item.license_ref is not None})
    if "synthetic_rehearsal_only" in notes:
        evidence_passed, evidence_reason = False, "synthetic_evidence_not_promotable"
    elif "testnet_evidence_rehearsal" in notes:
        evidence_passed, evidence_reason = False, "testnet_evidence_not_promotable"
    elif not evidence:
        evidence_passed, evidence_reason = False, "evaluation_evidence_missing"
    else:
        evidence_passed, evidence_reason = True, "recorded_evidence_present"

    policy_bound = (
        spec.risk_policy_ref == bundle.risk_policy_id
        and spec.execution_policy_ref == bundle.execution_policy_id
    )
    if not is_agent_run:
        completion_reason = "evaluation_run_not_agent"
    elif evaluation_complete:
        completion_reason = "evaluation_completed"
    else:
        completion_reason = "evaluation_run_not_completed"
    if not evidence:
        entitlement_reason = "provider_evidence_missing"
    elif {"kavrigo-synthetic", "binance-spot-testnet"} & set(providers):
        entitlement_reason = "provider_scope_not_eligible"
    else:
        entitlement_reason = "provider_entitlement_not_configured"

    gates = [
        _gate("policy_approval_integrity", True, "approved_policy_verified"),
        _gate(
            "version_policy_binding",
            policy_bound,
            "policy_refs_match" if policy_bound else "policy_refs_do_not_match",
        ),
        _gate("evaluation_completion", evaluation_complete, completion_reason),
        _gate(
            "evaluation_version_binding",
            version_bound,
            "evaluation_version_matches" if version_bound else "evaluation_version_mismatch",
        ),
        _gate("promotable_evidence", evidence_passed, evidence_reason),
        _gate("provider_entitlement", False, entitlement_reason),
        _gate("activation_support", False, "paper_activation_not_implemented"),
    ]
    gate_documents = [gate.model_dump(mode="json") for gate in gates]
    decision = "eligible" if all(gate.passed for gate in gates) else "blocked"
    row = PaperActivationAssessment(
        assessment_id=assessment_id,
        workspace_id=context.workspace_id,
        agent_id=agent_id,
        agent_version_id=version_row.agent_version_id,
        version=version,
        bundle_id=bundle.bundle_id,
        approval_id=approval.approval_id,
        evaluation_run_id=body.evaluation_run_id,
        agent_spec_hash=version_row.spec_hash,
        risk_hash=bundle.risk_hash,
        execution_hash=bundle.execution_hash,
        evaluation_input_hash=found["input_hash"],
        evaluation_output_hash=evaluation_output_hash,
        providers=providers,
        license_refs=license_refs,
        gate_results=gate_documents,
        gate_hash=content_hash(gate_documents),
        decision=decision,
        reason=body.reason,
        idempotency_key=key,
        request_hash=fingerprint,
        assessed_by=context.user_id,
    )
    await assessments.insert(row)
    await AuditRepository(session, context.workspace_id).record(
        action="paper_activation_assessed",
        actor=context.user_id,
        subject_type="agent_version",
        subject_id=version_row.agent_version_id,
        reason=body.reason,
        request_id=getattr(request.state, "request_id", None),
        payload={
            "assessment_id": assessment_id,
            "decision": decision,
            "failed_gates": [gate.gate for gate in gates if not gate.passed],
            "execution_enabled": False,
        },
    )
    _log.info(
        "paper_activation_assessed",
        decision=decision,
        failed_gate_count=sum(not gate.passed for gate in gates),
        execution_enabled=False,
    )
    return _response(row)


@router.get(
    "/{agent_id}/versions/{version}/paper-activation-assessments/{assessment_id}",
    response_model=PaperActivationAssessmentResponse,
    summary="Read one immutable paper-activation eligibility assessment",
)
async def get_paper_activation_assessment(
    agent_id: AgentPath,
    version: VersionPath,
    assessment_id: AssessmentPath,
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.AGENT_READ))],
) -> PaperActivationAssessmentResponse:
    row = await PaperActivationRepository(session, context.workspace_id).get(assessment_id)
    if row is None or row.agent_id != agent_id or row.version != version:
        raise ApiError(ErrorCode.NOT_FOUND, "Activation assessment not found.", 404)
    return _response(row)
