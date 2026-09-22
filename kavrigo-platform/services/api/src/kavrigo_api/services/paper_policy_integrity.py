"""Integrity checks shared by paper-policy reads and activation assessment."""

from kavrigo_api.db.models import PaperPolicyApproval, PaperPolicyBundle, PaperPolicyReview
from kavrigo_api.errors import ApiError, ErrorCode
from kavrigo_domain import RiskPolicy, RiskScope, content_hash
from kavrigo_risk import RiskExecutionPolicy, policy_hash

__all__ = ["validate_approval", "validate_review", "validated_bundle"]


def validated_bundle(row: PaperPolicyBundle) -> tuple[RiskPolicy, RiskExecutionPolicy]:
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
    return risk, execution


def validate_review(row: PaperPolicyReview, bundle: PaperPolicyBundle) -> None:
    validated_bundle(bundle)
    if (
        row.workspace_id != bundle.workspace_id
        or row.bundle_id != bundle.bundle_id
        or row.risk_hash != bundle.risk_hash
        or row.execution_hash != bundle.execution_hash
        or row.reviewed_by == bundle.created_by
    ):
        raise ApiError(ErrorCode.CONFLICT, "Stored policy review integrity check failed.", 409)


def validate_approval(
    row: PaperPolicyApproval, review: PaperPolicyReview, bundle: PaperPolicyBundle
) -> None:
    validate_review(review, bundle)
    if (
        review.recommendation != "advance_to_evaluation"
        or row.workspace_id != bundle.workspace_id
        or row.bundle_id != bundle.bundle_id
        or row.review_id != review.review_id
        or row.risk_hash != bundle.risk_hash
        or row.execution_hash != bundle.execution_hash
        or row.approved_by != review.reviewed_by
    ):
        raise ApiError(ErrorCode.CONFLICT, "Stored policy approval integrity check failed.", 409)
