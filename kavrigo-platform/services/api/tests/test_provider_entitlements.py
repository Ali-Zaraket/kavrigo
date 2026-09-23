"""Deterministic, fail-closed provider-entitlement evaluation."""

from datetime import UTC, datetime, timedelta

import pytest

from kavrigo_api.db.models import DataEntitlementEvent
from kavrigo_api.errors import ApiError
from kavrigo_api.services.provider_entitlements import (
    DataEntitlementEventDocument,
    ProviderEntitlementDecision,
    entitlement_event_hash,
    evaluate_provider_entitlements,
)
from kavrigo_domain import DataPack, EvidenceItem, EvidenceKind, SourceClass

WORKSPACE_ID = "ws_" + "1" * 32
PROVIDER = "licensed-fixture"
LICENSE_REF = "licensed-fixture-contract-v1"
EVIDENCE_AT = datetime(2026, 9, 20, 12, tzinfo=UTC)
ASSESSED_AT = EVIDENCE_AT + timedelta(days=1)
PACKS = (DataPack.MARKET_MICROSTRUCTURE, DataPack.PRICE_TECHNICAL)
RIGHTS = ("agent_decision", "application_display", "derived_data", "historical_storage")


def _evidence() -> tuple[EvidenceItem, ...]:
    return (
        EvidenceItem(
            evidence_id="ev_" + "2" * 32,
            kind=EvidenceKind.PRICE_TECHNICAL,
            source_class=SourceClass.MARKET_DATA,
            provider=PROVIDER,
            summary="Licensed fixture market evidence for entitlement evaluation.",
            observed_at=EVIDENCE_AT,
            ingested_at=EVIDENCE_AT,
            content_hash="sha256:" + "3" * 64,
            quality=1,
            confidence=1,
            license_ref=LICENSE_REF,
        ),
    )


def _row(
    *,
    suffix: str,
    scope: str,
    action: str = "grant",
    effective_at: datetime = EVIDENCE_AT - timedelta(days=1),
    expires_at: datetime | None = ASSESSED_AT + timedelta(days=1),
    rights: tuple[str, ...] | None = None,
    data_packs: tuple[DataPack, ...] | None = None,
) -> DataEntitlementEvent:
    if action == "revoke":
        rights = ()
        data_packs = ()
        contract_hash = None
    elif scope == "platform":
        rights = RIGHTS if rights is None else rights
        data_packs = PACKS if data_packs is None else data_packs
        contract_hash = "sha256:" + "4" * 64
    else:
        rights = ()
        data_packs = PACKS if data_packs is None else data_packs
        contract_hash = None
    document = DataEntitlementEventDocument(
        event_id="dee_" + suffix * 32,
        workspace_id=WORKSPACE_ID if scope == "workspace" else None,
        scope=scope,
        action=action,
        provider=PROVIDER,
        license_ref=LICENSE_REF,
        rights=rights,
        data_packs=data_packs,
        contract_hash=contract_hash,
        effective_at=effective_at,
        expires_at=expires_at,
        reason="Test-only entitlement history event with a concrete operator reason.",
        recorded_by="test-compliance-operator",
    )
    values = document.model_dump(mode="python")
    values["rights"] = list(document.rights)
    values["data_packs"] = [pack.value for pack in document.data_packs]
    return DataEntitlementEvent(
        **values,
        event_hash=entitlement_event_hash(document),
    )


def _evaluate(rows: list[DataEntitlementEvent]) -> ProviderEntitlementDecision:
    return evaluate_provider_entitlements(
        rows,
        workspace_id=WORKSPACE_ID,
        evidence=_evidence(),
        data_packs=PACKS,
        evidence_at=EVIDENCE_AT,
        assessed_at=ASSESSED_AT,
    )


def test_exact_platform_and_workspace_grants_pass() -> None:
    result = _evaluate([_row(suffix="a", scope="platform"), _row(suffix="b", scope="workspace")])

    assert result.passed is True
    assert result.reason_code == "provider_entitlement_verified"
    assert {(ref.scope, ref.event_id) for ref in result.event_refs} == {
        ("platform", "dee_" + "a" * 32),
        ("workspace", "dee_" + "b" * 32),
    }


def test_revocation_after_evidence_blocks_current_activation() -> None:
    result = _evaluate(
        [
            _row(suffix="a", scope="platform"),
            _row(
                suffix="c",
                scope="platform",
                action="revoke",
                effective_at=EVIDENCE_AT + timedelta(hours=1),
                expires_at=None,
            ),
            _row(suffix="b", scope="workspace"),
        ]
    )

    assert result.passed is False
    assert result.reason_code == "provider_license_inactive"
    assert result.event_refs == ()


def test_each_provider_must_cover_every_requested_data_pack() -> None:
    result = _evaluate(
        [
            _row(
                suffix="a",
                scope="platform",
                data_packs=(DataPack.MARKET_MICROSTRUCTURE,),
            ),
            _row(suffix="b", scope="workspace"),
        ]
    )

    assert result.passed is False
    assert result.reason_code == "data_pack_not_entitled"


def test_corrupt_event_hash_fails_closed() -> None:
    platform = _row(suffix="a", scope="platform")
    platform.event_hash = "sha256:" + "f" * 64

    with pytest.raises(ApiError, match="integrity check failed"):
        _evaluate([platform, _row(suffix="b", scope="workspace")])
