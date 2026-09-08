"""Validate immutable input boundaries before model calls. No unknown state is permission."""

from datetime import datetime
from decimal import Decimal, localcontext

from kavrigo_domain import AgentVersion, DataPack, EvidenceItem, MarketSnapshot, content_hash
from kavrigo_domain.evidence import EvidenceKind
from kavrigo_domain.numeric import DECIMAL_CONTEXT
from kavrigo_runtime.contracts import EvaluationRequest, NetworkContext, RuntimePolicy

_PACKS = {
    EvidenceKind.PRICE_TECHNICAL: DataPack.PRICE_TECHNICAL,
    EvidenceKind.ORDER_FLOW: DataPack.MARKET_MICROSTRUCTURE,
    EvidenceKind.DERIVATIVES: DataPack.DERIVATIVES,
    EvidenceKind.ONCHAIN: DataPack.ONCHAIN_CORE,
    EvidenceKind.STABLECOIN: DataPack.STABLECOINS,
    EvidenceKind.ETF_FLOW: DataPack.ETF_FLOWS,
    EvidenceKind.TOKENOMICS: DataPack.TOKENOMICS,
    EvidenceKind.DEFI: DataPack.DEFI,
    EvidenceKind.NETWORK_EVENT: DataPack.ONCHAIN_CORE,
    EvidenceKind.EXCHANGE_EVENT: DataPack.NEWS,
    EvidenceKind.SECURITY_EVENT: DataPack.SECURITY_EVENTS,
    EvidenceKind.NEWS: DataPack.NEWS,
    EvidenceKind.MACRO: DataPack.MACRO,
    EvidenceKind.REGULATION: DataPack.NEWS,
    EvidenceKind.GEOPOLITICAL: DataPack.MACRO,
    EvidenceKind.SOCIAL_ATTENTION: DataPack.SOCIAL_ATTENTION,
    EvidenceKind.RELATIVE_STRENGTH: DataPack.RELATIVE_STRENGTH,
}


def snapshot_hash(snapshot: MarketSnapshot) -> str:
    return content_hash(snapshot.model_dump(mode="python", exclude={"content_hash"}))


def network_hash(context: NetworkContext) -> str:
    return content_hash(context.model_dump(mode="python", exclude={"content_hash"}))


def input_reason(
    request: EvaluationRequest, version: AgentVersion, policy: RuntimePolicy, now: datetime
) -> str | None:
    snapshot, portfolio = request.snapshot, request.portfolio
    if now.tzinfo is None or snapshot.as_of > now:
        return "future_snapshot"
    if (
        request.workspace_id != version.workspace_id
        or portfolio.workspace_id != version.workspace_id
    ):
        return "workspace_mismatch"
    if portfolio.mode != version.spec.mode:
        return "mode_mismatch"
    if portfolio.base_currency != "USD":
        return "unsupported_valuation_currency"
    for position in portfolio.positions:
        mark = position.mark_price
        if (
            position.quantity.value < 0
            or mark is None
            or (mark.base, mark.quote) != (position.instrument_id.base, portfolio.base_currency)
        ):
            return "unknown_position_valuation"
        if position.opened_at is not None and position.opened_at > snapshot.as_of:
            return "future_position"
    with localcontext(DECIMAL_CONTEXT):
        exposure = sum(
            (
                position.market_value.amount
                for position in portfolio.positions
                if position.market_value is not None
            ),
            Decimal(0),
        )
        if (
            portfolio.equity.amount != portfolio.cash.amount + exposure
            or portfolio.gross_exposure.amount != exposure
            or portfolio.net_exposure.amount != exposure
        ):
            return "inconsistent_portfolio"
    if request.horizon_minutes not in version.spec.analysis.horizons_minutes:
        return "unsupported_horizon"
    if portfolio.as_of > snapshot.as_of:
        return "future_portfolio"
    if (snapshot.as_of - portfolio.as_of).total_seconds() * 1000 > policy.max_portfolio_age_ms:
        return "stale_portfolio"
    if (now - snapshot.as_of).total_seconds() * 1000 > policy.max_snapshot_age_ms:
        return "stale_snapshot"
    if portfolio.reconciled_at is not None and portfolio.reconciled_at > snapshot.as_of:
        return "future_reconciliation"
    if not portfolio.is_reconciled or portfolio.reconciled_at is None:
        return "unknown_portfolio"
    if (now - portfolio.reconciled_at).total_seconds() * 1000 > policy.max_portfolio_age_ms:
        return "stale_reconciliation"
    if snapshot.content_hash != snapshot_hash(snapshot):
        return "snapshot_hash_mismatch"
    if len({i.value for i in snapshot.instruments}) != len(snapshot.instruments):
        return "duplicate_instrument"
    if len({f.instrument_id.value for f in snapshot.features}) != len(snapshot.features):
        return "duplicate_feature_vector"
    for feature in snapshot.features:
        if feature.feature_set_version != version.feature_set_version:
            return "feature_version_mismatch"
        if feature.content_hash != content_hash(
            {
                "instrument_id": feature.instrument_id.value,
                "feature_set_version": feature.feature_set_version,
                "values": feature.values,
            }
        ):
            return "feature_hash_mismatch"
    if set(snapshot.evidence_refs) != {e.evidence_id for e in request.evidence}:
        return "evidence_snapshot_mismatch"
    if len({e.evidence_id for e in request.evidence}) != len(request.evidence):
        return "duplicate_evidence"
    if any(
        e.ingested_at > snapshot.as_of or e.observed_at > snapshot.as_of for e in request.evidence
    ):
        return "future_evidence"
    if any(
        e.news_event is not None and e.news_event.first_seen_at > e.ingested_at
        for e in request.evidence
    ):
        return "future_news_arrival"
    quality = snapshot.quality
    if (
        not quality.provider_health_ok
        or not quality.sequence_complete
        or quality.freshness.stale_families
        or quality.freshness.missing_families
    ):
        return "unhealthy_snapshot"
    return None


def eligible_evidence(
    request: EvaluationRequest, version: AgentVersion
) -> tuple[EvidenceItem, ...]:
    return tuple(
        sorted(
            (
                item
                for item in request.evidence
                if _PACKS[item.kind] in version.spec.data_packs
                and item.quality >= version.spec.evidence.min_source_quality
                and not item.injection_signals
            ),
            key=lambda item: item.evidence_id,
        )
    )
