"""Point-in-time provider and workspace data-entitlement evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from kavrigo_api.db.models import DataEntitlementEvent
from kavrigo_api.errors import ApiError, ErrorCode
from kavrigo_api.schemas.paper_activation import PaperActivationEntitlementRef
from kavrigo_domain import DataPack, DomainModel, EvidenceItem, UtcDatetime, content_hash

__all__ = [
    "DataEntitlementEventDocument",
    "ProviderEntitlementDecision",
    "entitlement_event_hash",
    "evaluate_provider_entitlements",
]

type EntitlementRight = Literal[
    "application_display",
    "derived_data",
    "agent_decision",
    "historical_storage",
]

REQUIRED_AGENT_RIGHTS: frozenset[EntitlementRight] = frozenset(
    {"application_display", "derived_data", "agent_decision", "historical_storage"}
)


class DataEntitlementEventDocument(DomainModel):
    """Canonical content of one operator-controlled entitlement event."""

    event_id: Annotated[str, Field(pattern=r"^dee_[0-9a-f]{32}$")]
    workspace_id: Annotated[str | None, Field(pattern=r"^ws_[0-9a-f]{32}$")] = None
    scope: Literal["platform", "workspace"]
    action: Literal["grant", "revoke"]
    provider: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
    license_ref: Annotated[str, Field(min_length=1, max_length=128)]
    rights: Annotated[tuple[EntitlementRight, ...], Field(max_length=4)] = ()
    data_packs: Annotated[tuple[DataPack, ...], Field(max_length=13)] = ()
    contract_hash: Annotated[str | None, Field(pattern=r"^sha256:[0-9a-f]{64}$")] = None
    effective_at: UtcDatetime
    expires_at: UtcDatetime | None = None
    reason: Annotated[str, Field(min_length=10, max_length=2000)]
    recorded_by: Annotated[str, Field(min_length=1, max_length=128)]

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if (self.scope == "platform") != (self.workspace_id is None):
            raise ValueError("platform events are global; workspace events require a workspace")
        if self.expires_at is not None and self.expires_at <= self.effective_at:
            raise ValueError("entitlement expiry must follow its effective time")
        if len(set(self.rights)) != len(self.rights) or tuple(sorted(self.rights)) != self.rights:
            raise ValueError("entitlement rights must be sorted and unique")
        if (
            len(set(self.data_packs)) != len(self.data_packs)
            or tuple(sorted(self.data_packs, key=str)) != self.data_packs
        ):
            raise ValueError("entitlement data packs must be sorted and unique")
        if self.action == "revoke":
            if self.rights or self.data_packs or self.contract_hash is not None:
                raise ValueError("revocation events carry no rights, packs, or contract hash")
            return self
        if not self.data_packs:
            raise ValueError("grant events require at least one data pack")
        if self.scope == "platform":
            if not self.rights or self.contract_hash is None:
                raise ValueError("platform grants require rights and a contract hash")
        elif self.rights or self.contract_hash is not None:
            raise ValueError("workspace grants inherit platform rights and contract identity")
        return self


@dataclass(frozen=True)
class ProviderEntitlementDecision:
    passed: bool
    reason_code: str
    event_refs: tuple[PaperActivationEntitlementRef, ...] = ()


@dataclass(frozen=True)
class _ValidatedEvent:
    document: DataEntitlementEventDocument
    event_hash: str


def entitlement_event_hash(document: DataEntitlementEventDocument) -> str:
    return content_hash(document)


def _validated(row: DataEntitlementEvent) -> _ValidatedEvent:
    document = DataEntitlementEventDocument(
        event_id=row.event_id,
        workspace_id=row.workspace_id,
        scope=row.scope,
        action=row.action,
        provider=row.provider,
        license_ref=row.license_ref,
        rights=tuple(row.rights),
        data_packs=tuple(row.data_packs),
        contract_hash=row.contract_hash,
        effective_at=row.effective_at,
        expires_at=row.expires_at,
        reason=row.reason,
        recorded_by=row.recorded_by,
    )
    if entitlement_event_hash(document) != row.event_hash:
        raise ApiError(ErrorCode.CONFLICT, "Stored data entitlement integrity check failed.", 409)
    return _ValidatedEvent(document=document, event_hash=row.event_hash)


def _effective(
    events: tuple[_ValidatedEvent, ...],
    *,
    scope: Literal["platform", "workspace"],
    workspace_id: str,
    provider: str,
    license_ref: str,
    at: UtcDatetime,
) -> _ValidatedEvent | None:
    candidates = [
        event
        for event in events
        if event.document.scope == scope
        and event.document.workspace_id == (workspace_id if scope == "workspace" else None)
        and event.document.provider == provider
        and event.document.license_ref == license_ref
        and event.document.effective_at <= at
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: (item.document.effective_at, item.document.event_id))
    if latest.document.action == "revoke":
        return None
    if latest.document.expires_at is not None and latest.document.expires_at <= at:
        return None
    return latest


def _ref(event: _ValidatedEvent) -> PaperActivationEntitlementRef:
    document = event.document
    return PaperActivationEntitlementRef(
        event_id=document.event_id,
        event_hash=event.event_hash,
        scope=document.scope,
        provider=document.provider,
        license_ref=document.license_ref,
    )


def evaluate_provider_entitlements(
    rows: list[DataEntitlementEvent],
    *,
    workspace_id: str,
    evidence: tuple[EvidenceItem, ...],
    data_packs: tuple[DataPack, ...],
    evidence_at: UtcDatetime,
    assessed_at: UtcDatetime,
) -> ProviderEntitlementDecision:
    """Require legal platform rights and tenant access at evidence and assessment time."""
    if not evidence:
        return ProviderEntitlementDecision(False, "provider_evidence_missing")
    if any(item.license_ref is None for item in evidence):
        return ProviderEntitlementDecision(False, "evidence_license_ref_missing")

    events = tuple(_validated(row) for row in rows)
    pairs = sorted(
        (item.provider, item.license_ref) for item in evidence if item.license_ref is not None
    )
    selected: dict[str, _ValidatedEvent] = {}
    required_packs = set(data_packs)

    for provider, license_ref in pairs:
        platform_at_evidence = _effective(
            events,
            scope="platform",
            workspace_id=workspace_id,
            provider=provider,
            license_ref=license_ref,
            at=evidence_at,
        )
        if platform_at_evidence is None:
            return ProviderEntitlementDecision(False, "provider_license_not_effective_for_evidence")
        platform_now = _effective(
            events,
            scope="platform",
            workspace_id=workspace_id,
            provider=provider,
            license_ref=license_ref,
            at=assessed_at,
        )
        if platform_now is None:
            return ProviderEntitlementDecision(False, "provider_license_inactive")
        if not REQUIRED_AGENT_RIGHTS.issubset(platform_at_evidence.document.rights) or not (
            REQUIRED_AGENT_RIGHTS.issubset(platform_now.document.rights)
        ):
            return ProviderEntitlementDecision(False, "provider_rights_insufficient")

        workspace_at_evidence = _effective(
            events,
            scope="workspace",
            workspace_id=workspace_id,
            provider=provider,
            license_ref=license_ref,
            at=evidence_at,
        )
        if workspace_at_evidence is None:
            return ProviderEntitlementDecision(
                False, "workspace_entitlement_not_effective_for_evidence"
            )
        workspace_now = _effective(
            events,
            scope="workspace",
            workspace_id=workspace_id,
            provider=provider,
            license_ref=license_ref,
            at=assessed_at,
        )
        if workspace_now is None:
            return ProviderEntitlementDecision(False, "workspace_entitlement_inactive")

        allowed_by_platform = set(platform_at_evidence.document.data_packs) & set(
            platform_now.document.data_packs
        )
        allowed_by_workspace = set(workspace_at_evidence.document.data_packs) & set(
            workspace_now.document.data_packs
        )
        if not required_packs.issubset(allowed_by_platform & allowed_by_workspace):
            return ProviderEntitlementDecision(False, "data_pack_not_entitled")
        for event in (
            platform_at_evidence,
            platform_now,
            workspace_at_evidence,
            workspace_now,
        ):
            selected[event.document.event_id] = event

    refs = tuple(_ref(selected[event_id]) for event_id in sorted(selected))
    return ProviderEntitlementDecision(True, "provider_entitlement_verified", refs)
