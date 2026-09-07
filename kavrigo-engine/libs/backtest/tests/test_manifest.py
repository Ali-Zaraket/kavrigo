"""Dataset manifests and leakage detection."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from kavrigo_backtest import DatasetManifest, TimeBasis

from .conftest import END, START, manifest, source


class TestLeakageDetection:
    def test_a_clean_dataset_is_safe(self, default_manifest: DatasetManifest) -> None:
        assert default_manifest.leakage_findings() == []
        assert default_manifest.is_point_in_time_safe

    def test_cutting_on_event_time_is_flagged(self) -> None:
        """The subtle one: it looks correct and silently includes records that only reached the
        platform later, handing the strategy information nobody had."""
        found = manifest(time_basis=TimeBasis.EVENT_TIME).leakage_findings()
        assert [f.code for f in found] == ["not_point_in_time"]

    def test_provider_revisions_are_flagged(self) -> None:
        """A revision encodes what was learned after the fact (spec 8.5)."""
        found = manifest(sources=[source(contains_revisions=True)]).leakage_findings()
        assert [f.code for f in found] == ["contains_provider_revisions"]

    def test_events_after_the_period_are_flagged(self) -> None:
        found = manifest(
            sources=[source(last_event_time=END + timedelta(days=1))]
        ).leakage_findings()
        assert "event_after_period" in [f.code for f in found]

    def test_ingestion_after_the_period_is_flagged(self) -> None:
        found = manifest(
            sources=[source(last_ingested_at=END + timedelta(hours=2))]
        ).leakage_findings()
        assert "ingested_after_period" in [f.code for f in found]

    def test_every_problem_is_reported_not_just_the_first(self) -> None:
        """A single 'unsafe' flag invites silencing the check rather than fixing the cause."""
        found = manifest(
            time_basis=TimeBasis.EVENT_TIME,
            sources=[source(contains_revisions=True, last_event_time=END + timedelta(days=1))],
        ).leakage_findings()
        codes = {f.code for f in found}
        assert codes == {
            "not_point_in_time",
            "contains_provider_revisions",
            "event_after_period",
        }

    def test_findings_name_the_offending_source(self) -> None:
        found = manifest(
            sources=[source(dataset="kavrigo.market_quotes", contains_revisions=True)]
        ).leakage_findings()
        assert found[0].source == "kavrigo.market_quotes"


class TestManifestHash:
    def test_the_hash_is_stable(self, default_manifest: DatasetManifest) -> None:
        reparsed = DatasetManifest.model_validate(default_manifest.model_dump())
        assert reparsed.manifest_hash == default_manifest.manifest_hash

    def test_source_order_does_not_change_the_hash(self) -> None:
        a = source(dataset="kavrigo.market_trades")
        b = source(dataset="kavrigo.market_quotes")
        assert manifest(sources=[a, b]).manifest_hash == manifest(sources=[b, a]).manifest_hash

    def test_different_data_gives_a_different_hash(self, default_manifest: DatasetManifest) -> None:
        """Two runs claiming the same manifest must really have seen the same bytes."""
        changed = manifest(sources=[source(content_hash="sha256:" + "cd" * 32)])
        assert changed.manifest_hash != default_manifest.manifest_hash

    def test_the_period_is_part_of_the_identity(self, default_manifest: DatasetManifest) -> None:
        shifted = manifest(period_end=END + timedelta(days=1))
        assert shifted.manifest_hash != default_manifest.manifest_hash


class TestValidation:
    def test_an_inverted_period_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="period_end must be after"):
            manifest(period_end=START)

    def test_a_source_with_an_inverted_range_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="precedes first_event_time"):
            source(last_event_time=START - timedelta(days=1))

    def test_a_manifest_needs_at_least_one_source(self) -> None:
        with pytest.raises(ValidationError):
            manifest(sources=[])

    def test_unlicensed_sources_are_listed(self) -> None:
        """Development can proceed; production cannot (spec 8.3)."""
        unlicensed = manifest(sources=[source(license_ref=None)])
        assert unlicensed.unlicensed_sources() == ["kavrigo.market_trades"]
        assert manifest().unlicensed_sources() == []

    def test_total_rows_sums_the_sources(self) -> None:
        combined = manifest(sources=[source(row_count=10), source(dataset="q", row_count=5)])
        assert combined.total_rows == 15
