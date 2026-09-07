"""Dataset manifests: what a run was allowed to see, and proof of it.

``MASTER_BUILD_SPEC.md`` §12.2 requires every backtest to record the dataset snapshot and its
hash. §12.3 requires that the run cannot use future or revised knowledge. A manifest is how both
are made checkable rather than asserted.

The distinction that does the work is §8.5's three timestamps:

* ``event_time`` — when the thing happened at the source;
* ``ingested_at`` — when the platform first saw it, which is when it became *knowable*;
* ``provider_revision_time`` — when the provider last changed the record.

A dataset built by filtering on ``event_time`` looks correct and is not: it silently includes
records that only reached the platform later, handing the strategy information nobody had. A
dataset containing provider revisions is worse, because the revision encodes what was learned
afterwards. Both are refused here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from kavrigo_domain import DomainModel, UtcDatetime, content_hash

__all__ = [
    "DatasetManifest",
    "DatasetSource",
    "LeakageFinding",
    "TimeBasis",
]


class TimeBasis(StrEnum):
    """Which timestamp a dataset was cut on.

    ``INGESTED_AT`` is the only basis that is honest about knowability. ``EVENT_TIME`` is
    representable so a manifest can *record* that a dataset was built the wrong way — a
    provenance system that cannot describe a bad dataset cannot flag one.
    """

    INGESTED_AT = "ingested_at"
    EVENT_TIME = "event_time"

    @property
    def is_point_in_time(self) -> bool:
        return self is TimeBasis.INGESTED_AT


class DatasetSource(DomainModel):
    """One provider feed contributing to a dataset."""

    provider: Annotated[str, Field(min_length=1, max_length=64)]
    venue: Annotated[str | None, Field(default=None, max_length=32)] = None
    dataset: Annotated[str, Field(min_length=1, max_length=128)]
    """The table or file set, e.g. ``kavrigo.market_trades``."""

    row_count: Annotated[int, Field(ge=0)]
    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    first_event_time: UtcDatetime
    last_event_time: UtcDatetime
    last_ingested_at: UtcDatetime
    contains_revisions: bool = False
    """True if any row was a provider revision. A revision encodes what was learned later
    (``MASTER_BUILD_SPEC.md`` §8.5), so a point-in-time dataset must not contain one."""

    license_ref: Annotated[str | None, Field(default=None, max_length=128)] = None
    """Which data-licence entry permits retaining this snapshot. ``None`` is acceptable in
    development and is a launch blocker in production (§8.3)."""

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.last_event_time < self.first_event_time:
            raise ValueError("last_event_time precedes first_event_time")
        if self.row_count == 0 and self.first_event_time != self.last_event_time:
            raise ValueError("an empty source cannot span a time range")
        return self


class LeakageFinding(DomainModel):
    """One reason a dataset is not safe for a historical run."""

    code: Annotated[str, Field(min_length=1, max_length=64)]
    detail: Annotated[str, Field(min_length=1, max_length=500)]
    source: Annotated[str | None, Field(default=None, max_length=128)] = None


class DatasetManifest(DomainModel):
    """A frozen, hashed description of the data a run may read.

    ``manifest_hash`` covers every source hash, so two runs claiming the same manifest really
    did see the same bytes. That is the difference between a reproducible result and a
    reproducible *claim*.
    """

    manifest_id: Annotated[str, Field(pattern=r"^ds_[0-9a-f]{32}$")]
    created_at: UtcDatetime
    period_start: UtcDatetime
    period_end: UtcDatetime
    time_basis: TimeBasis = TimeBasis.INGESTED_AT
    sources: Annotated[list[DatasetSource], Field(min_length=1, max_length=64)]
    instruments: Annotated[list[str], Field(min_length=1, max_length=512)]
    feature_set_version: Annotated[str, Field(pattern=r"^v\d+(\.\d+)*$")]
    notes: Annotated[str, Field(max_length=2000)] = ""

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self

    @property
    def manifest_hash(self) -> str:
        """Content hash over the sources and period — the run's data fingerprint."""
        return content_hash(
            {
                "period_start": self.period_start,
                "period_end": self.period_end,
                "time_basis": self.time_basis.value,
                "feature_set_version": self.feature_set_version,
                "instruments": sorted(self.instruments),
                "sources": sorted(
                    (
                        {
                            "provider": s.provider,
                            "dataset": s.dataset,
                            "row_count": s.row_count,
                            "content_hash": s.content_hash,
                        }
                        for s in self.sources
                    ),
                    key=lambda entry: (entry["provider"], entry["dataset"]),
                ),
            }
        )

    @property
    def total_rows(self) -> int:
        return sum(source.row_count for source in self.sources)

    def leakage_findings(self) -> list[LeakageFinding]:
        """Every reason this dataset is unsafe for a historical run.

        A list rather than a boolean: a researcher fixing one problem needs to see the others,
        and a single "unsafe" flag invites the fix that silences the check without addressing
        the cause.
        """
        findings: list[LeakageFinding] = []

        if not self.time_basis.is_point_in_time:
            findings.append(
                LeakageFinding(
                    code="not_point_in_time",
                    detail=(
                        "Dataset was cut on event_time, which includes records that only reached "
                        "the platform later. Cut on ingested_at instead."
                    ),
                )
            )

        for source in self.sources:
            if source.contains_revisions:
                findings.append(
                    LeakageFinding(
                        code="contains_provider_revisions",
                        detail=(
                            "Source contains provider revisions, which encode information learned "
                            "after the fact (MASTER_BUILD_SPEC.md 8.5)."
                        ),
                        source=source.dataset,
                    )
                )
            if source.last_ingested_at > self.period_end:
                findings.append(
                    LeakageFinding(
                        code="ingested_after_period",
                        detail=(
                            f"Source was still ingesting at {source.last_ingested_at.isoformat()}, "
                            f"after the period ended at {self.period_end.isoformat()}."
                        ),
                        source=source.dataset,
                    )
                )
            if source.last_event_time > self.period_end:
                findings.append(
                    LeakageFinding(
                        code="event_after_period",
                        detail=(
                            f"Source holds an event at {source.last_event_time.isoformat()}, "
                            f"after the period ended at {self.period_end.isoformat()}."
                        ),
                        source=source.dataset,
                    )
                )

        return findings

    @property
    def is_point_in_time_safe(self) -> bool:
        return not self.leakage_findings()

    def unlicensed_sources(self) -> list[str]:
        """Sources with no recorded licence entry (``MASTER_BUILD_SPEC.md`` §8.3)."""
        return [s.dataset for s in self.sources if s.license_ref is None]


def dataset_content_hash(rows: object) -> str:
    """Hash of the raw rows a source contributed, for the manifest's ``content_hash``."""
    return content_hash(rows)
