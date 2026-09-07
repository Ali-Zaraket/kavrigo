"""The immutable audit record (``MASTER_BUILD_SPEC.md`` §25).

Every decision must be reconstructable: which data, prompt, model, policy and code produced it.
This record is append-only and is the platform's source of truth for what happened — Langfuse
traces and Temporal histories are operational aids, not the ledger (ADR 0011).

The rule this enforces is the product's central claim: *the same decision can be reproduced from
the recorded snapshot* (§1.2).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from kavrigo_domain.base import DomainModel, UtcDatetime
from kavrigo_domain.identifiers import (
    AgentId,
    AgentVersionId,
    DecisionId,
    EvidenceId,
    OrderId,
    OrderIntentId,
    SnapshotId,
    WorkspaceId,
)

__all__ = ["AuditAction", "AuditRecord"]


class AuditAction(StrEnum):
    """High-impact actions that must produce an audit event (``MASTER_BUILD_SPEC.md`` §53, §61)."""

    DECISION_RECORDED = "decision_recorded"
    RISK_EVALUATED = "risk_evaluated"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_STATE_CHANGED = "order_state_changed"
    AGENT_VERSION_CREATED = "agent_version_created"
    AGENT_PROMOTED = "agent_promoted"
    RISK_POLICY_CHANGED = "risk_policy_changed"
    KILL_SWITCH_TOGGLED = "kill_switch_toggled"
    EXCHANGE_CONNECTION_CHANGED = "exchange_connection_changed"
    LIVE_ELIGIBILITY_CHANGED = "live_eligibility_changed"
    ADMIN_OVERRIDE = "admin_override"


class AuditRecord(DomainModel):
    """One append-only audit entry.

    Fields are nullable where an action legitimately has no decision or order attached (a kill
    switch, say). Reproducibility fields are not optional for decision-related actions: without
    the container image digest and the policy versions, a historical decision cannot be replayed.
    """

    audit_id: Annotated[str, Field(min_length=1, max_length=64)]
    action: AuditAction
    workspace_id: WorkspaceId
    created_at: UtcDatetime
    actor: Annotated[str, Field(min_length=1, max_length=128)]
    """A user id, service name, or ``system``. Privileged actions require an identified actor."""

    reason: Annotated[str, Field(max_length=1000)] = ""
    """Required by policy for privileged/admin actions (``MASTER_BUILD_SPEC.md`` §53)."""

    decision_id: DecisionId | None = None
    agent_id: AgentId | None = None
    agent_version_id: AgentVersionId | None = None
    snapshot_id: SnapshotId | None = None
    order_intent_id: OrderIntentId | None = None
    order_id: OrderId | None = None
    evidence_ids: Annotated[list[EvidenceId], Field(max_length=512)] = []

    prompt_hash: Annotated[str | None, Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")] = None
    model_profile: Annotated[str | None, Field(default=None, max_length=32)] = None
    resolved_model_identifier: Annotated[str | None, Field(default=None, max_length=128)] = None
    tool_policy_version: Annotated[str | None, Field(default=None, max_length=32)] = None
    risk_policy_version: Annotated[str | None, Field(default=None, max_length=64)] = None
    execution_policy_version: Annotated[str | None, Field(default=None, max_length=64)] = None
    feature_set_version: Annotated[str | None, Field(default=None, max_length=32)] = None
    dataset_manifest_ref: Annotated[str | None, Field(default=None, max_length=256)] = None
    feature_vector_hash: Annotated[
        str | None, Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    ] = None
    tool_result_hashes: Annotated[list[str], Field(max_length=64)] = []
    container_image_digest: Annotated[str | None, Field(default=None, max_length=128)] = None
    trace_id: Annotated[str | None, Field(default=None, max_length=64)] = None
    payload_hash: Annotated[str | None, Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")] = (
        None
    )
