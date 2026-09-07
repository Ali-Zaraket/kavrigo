"""Point-in-time snapshots, freshness and the event envelope."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kavrigo_domain import (
    DataFamily,
    DataQuality,
    EventEnvelope,
    EventSource,
    EvidenceItem,
    EvidenceKind,
    FeatureVector,
    FreshnessReport,
    InstrumentId,
    MarketRegime,
    MarketSnapshot,
    NewsEvent,
    NewsEventType,
    SourceClass,
    SourceKind,
    TenantScope,
)
from kavrigo_domain.testing import AS_OF, HASH, oid

BTC = InstrumentId.parse("BTC-USDT.BINANCE")
ETH = InstrumentId.parse("ETH-USDT.BINANCE")


def _envelope(**overrides: object) -> EventEnvelope:
    base: dict[str, object] = {
        "event_id": "evt_1",
        "event_type": "market.trade.raw.v1",
        "source": EventSource(kind=SourceKind.EXCHANGE_STREAM, provider="binance", venue="BINANCE"),
        "event_time": AS_OF,
        "ingested_at": AS_OF + timedelta(milliseconds=40),
        "partition_key": "BINANCE:BTC-USDT",
        "payload": {"price": "60000", "quantity": "0.01"},
    }
    return EventEnvelope(**{**base, **overrides})  # type: ignore[arg-type]


class TestEventEnvelope:
    def test_ingest_cannot_precede_the_event(self) -> None:
        with pytest.raises(ValidationError, match="ingested_at precedes event_time"):
            _envelope(ingested_at=AS_OF - timedelta(seconds=1))

    def test_event_type_must_be_versioned(self) -> None:
        with pytest.raises(ValidationError):
            _envelope(event_type="market.trade.raw")

    def test_age_is_measured_from_event_time(self) -> None:
        envelope = _envelope()
        assert envelope.age_ms_at(AS_OF + timedelta(seconds=2)) == 2000

    def test_tenant_scope_is_optional_for_public_data(self) -> None:
        assert _envelope().tenant_scope is None
        scoped = _envelope(tenant_scope=TenantScope(workspace_id=oid("ws")))
        assert scoped.tenant_scope is not None

    def test_untrusted_sources_are_identifiable(self) -> None:
        assert SourceKind.NEWS_FEED.is_untrusted_content
        assert SourceKind.MCP_TOOL.is_untrusted_content
        assert not SourceKind.EXCHANGE_STREAM.is_untrusted_content

    def test_provider_revisions_are_distinguishable(self) -> None:
        source = EventSource(
            kind=SourceKind.DATA_PROVIDER,
            provider="example-onchain",
            provider_revision_time=AS_OF + timedelta(days=3),
            is_revision=True,
        )
        assert source.is_revision
        assert source.provider_revision_time is not None


class TestFreshness:
    def test_negative_ages_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="negative data age"):
            FreshnessReport(age_ms={DataFamily.TRADES: -1})

    def test_missing_and_stale_families_are_recorded(self) -> None:
        report = FreshnessReport(
            age_ms={DataFamily.TRADES: 900, DataFamily.NEWS: 1_200_000},
            stale_families=[DataFamily.NEWS],
            missing_families=[DataFamily.ONCHAIN],
        )
        assert report.age_for(DataFamily.NEWS) == 1_200_000
        assert report.age_for(DataFamily.ONCHAIN) is None


class TestMarketSnapshot:
    def _snapshot(self, **overrides: object) -> MarketSnapshot:
        base: dict[str, object] = {
            "snapshot_id": oid("snap"),
            "as_of": AS_OF,
            "created_at": AS_OF + timedelta(milliseconds=200),
            "instruments": [BTC],
            "quality": DataQuality(
                score=0.92,
                freshness=FreshnessReport(age_ms={DataFamily.TRADES: 800}),
            ),
            "content_hash": HASH,
            "regime": MarketRegime.RANGE,
        }
        return MarketSnapshot(**{**base, **overrides})  # type: ignore[arg-type]

    def test_creation_cannot_precede_as_of(self) -> None:
        with pytest.raises(ValidationError, match="created_at precedes as_of"):
            self._snapshot(created_at=AS_OF - timedelta(seconds=1))

    def test_features_must_be_in_the_snapshot_universe(self) -> None:
        stray = FeatureVector(
            instrument_id=ETH,
            feature_set_version="v1",
            values={"return_15m": Decimal("0.004")},
            content_hash=HASH,
        )
        with pytest.raises(ValidationError, match="not in the snapshot universe"):
            self._snapshot(features=[stray])

    def test_feature_values_reject_floats(self) -> None:
        with pytest.raises(ValidationError, match="binary float"):
            FeatureVector(
                instrument_id=BTC,
                feature_set_version="v1",
                values={"return_15m": 0.004},  # type: ignore[dict-item]
                content_hash=HASH,
            )

    def test_regime_labels_are_a_closed_set(self) -> None:
        with pytest.raises(ValidationError):
            self._snapshot(regime="euphoric_supercycle")

    def test_revised_data_is_flagged_for_leakage_review(self) -> None:
        quality = DataQuality(
            score=0.7,
            freshness=FreshnessReport(age_ms={DataFamily.ONCHAIN: 60_000}),
            contains_revised_data=True,
        )
        assert quality.contains_revised_data


class TestEvidence:
    def _evidence(self, **overrides: object) -> EvidenceItem:
        base: dict[str, object] = {
            "evidence_id": oid("ev"),
            "kind": EvidenceKind.DERIVATIVES,
            "source_class": SourceClass.MARKET_DATA,
            "provider": "example-derivatives",
            "summary": "Open interest rose 12% over 4h while funding stayed positive.",
            "instruments": [BTC],
            "observed_at": AS_OF,
            "ingested_at": AS_OF + timedelta(seconds=3),
            "content_hash": HASH,
            "quality": 0.86,
            "confidence": 0.72,
        }
        return EvidenceItem(**{**base, **overrides})  # type: ignore[arg-type]

    def test_ingest_cannot_precede_observation(self) -> None:
        with pytest.raises(ValidationError, match="ingested_at precedes observed_at"):
            self._evidence(ingested_at=AS_OF - timedelta(seconds=1))

    def test_news_payload_only_attaches_to_news_evidence(self) -> None:
        event = NewsEvent(
            event_type=NewsEventType.REGULATION,
            assets=["BTC"],
            importance=0.82,
            sentiment=-0.44,
            certainty=0.91,
            novelty=0.93,
            source_quality=0.95,
            expected_horizon="hours",
            published_at=AS_OF,
            first_seen_at=AS_OF + timedelta(minutes=2),
        )
        with pytest.raises(ValidationError, match="only be attached to NEWS evidence"):
            self._evidence(news_event=event)

        ok = self._evidence(kind=EvidenceKind.NEWS, news_event=event)
        assert ok.news_event is not None

    def test_injection_signals_are_recorded_not_acted_on(self) -> None:
        """Detections are provenance. The content still never becomes an instruction (§14)."""
        item = self._evidence(injection_signals=["imperative_to_agent", "ignore_previous"])
        assert item.injection_signals

    def test_news_cannot_be_seen_before_publication(self) -> None:
        with pytest.raises(ValidationError, match="first_seen_at precedes published_at"):
            NewsEvent(
                event_type=NewsEventType.LISTING,
                importance=0.5,
                sentiment=0.1,
                certainty=0.5,
                novelty=0.5,
                source_quality=0.5,
                expected_horizon="hours",
                published_at=AS_OF,
                first_seen_at=AS_OF - timedelta(minutes=1),
            )
