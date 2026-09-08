"""Internal feed/extraction contracts. No external provider payload is assumed (§42)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, Self

from pydantic import Field, model_validator

from kavrigo_domain import DomainModel, EvidenceItem, InstrumentId, ModelCallRecord
from kavrigo_domain.base import UtcDatetime
from kavrigo_domain.evidence import NewsEventType, Score, SignedScore, SourceClass
from kavrigo_domain.identifiers import WorkspaceId
from kavrigo_model_gateway.contracts import Digest, Name

Clock = Callable[[], datetime]
Text = Annotated[str, Field(min_length=1, max_length=32_768, repr=False)]


class RawArticle(DomainModel):
    article_id: Annotated[str, Field(min_length=1, max_length=256)]
    url: Annotated[str, Field(min_length=1, max_length=512, repr=False)]
    title: Annotated[str, Field(min_length=1, max_length=512, repr=False)]
    body_html: Annotated[str, Field(min_length=1, max_length=65_536, repr=False)]
    published_at: UtcDatetime | None
    first_seen_at: UtcDatetime


class FeedBatch(DomainModel):
    articles: Annotated[tuple[RawArticle, ...], Field(max_length=32)]


class FeedAdapter(Protocol):
    source_id: str

    async def read(self) -> FeedBatch:
        """One bounded batch. Transport retries/cursors belong to a verified adapter."""
        ...


class SourcePolicy(DomainModel):
    """Trusted registry entry, never parsed from an article or model answer."""

    source_id: Name
    version: Name
    allowed_hosts: Annotated[
        tuple[Annotated[str, Field(pattern=r"^[a-z0-9.-]+$")], ...],
        Field(min_length=1, max_length=32),
    ]
    source_class: Literal[
        SourceClass.OFFICIAL_PRIMARY,
        SourceClass.MAJOR_WIRE,
        SourceClass.SPECIALIST_PUBLICATION,
        SourceClass.PROJECT_SOCIAL,
        SourceClass.UNVERIFIED_SOCIAL,
    ]
    quality: Score
    license_ref: Annotated[str, Field(min_length=1, max_length=128)]
    rights: Literal["synthetic_fixture_only"] = "synthetic_fixture_only"


class Entity(DomainModel):
    entity_id: Name
    aliases: Annotated[
        tuple[Annotated[str, Field(min_length=2, max_length=64)], ...],
        Field(min_length=1, max_length=16),
    ]
    assets: Annotated[
        tuple[Annotated[str, Field(pattern=r"^[A-Z0-9]{2,16}$")], ...], Field(max_length=32)
    ] = ()
    instruments: Annotated[tuple[InstrumentId, ...], Field(max_length=32)] = ()

    @model_validator(mode="after")
    def _instrument_assets(self) -> Self:
        if any(item.base not in self.assets for item in self.instruments):
            raise ValueError("mapped instruments must belong to declared assets")
        return self


class ExtractionInput(DomainModel):
    text: Text
    known_entity_ids: Annotated[tuple[Name, ...], Field(max_length=64)]


class NewsExtraction(DomainModel):
    """Model-owned classification; the exact quote is checked against sanitized input.

    A quote establishes textual support, not truth. No authority, time or URL fields exist.
    """

    event_type: NewsEventType
    supporting_quote: Annotated[str, Field(min_length=10, max_length=1800, repr=False)]
    entity_ids: Annotated[tuple[Name, ...], Field(max_length=32)] = ()
    importance: Score
    sentiment: SignedScore
    certainty: Score
    expected_horizon: Literal["minutes", "hours", "days", "weeks", "unknown"]
    already_priced_in_likelihood: Score | None = None


class NewsRecord(DomainModel):
    """Frozen service output. Consumers use evidence.ingested_at for knowability.

    Must come from an authenticated store/service; hashes detect accidental corruption but do
    not authenticate a caller. No raw HTML is stored. The quote is still untrusted data.
    """

    workspace_id: WorkspaceId
    event_id: Annotated[str, Field(pattern=r"^evt_[0-9a-f]{32}$")]
    source_id: Name
    article_id: Annotated[str, Field(min_length=1, max_length=256)]
    source_policy_hash: Digest
    transform_version: Literal["news-text-v1"] = "news-text-v1"
    transform_hash: Digest
    article_hash: Digest
    entities: tuple[Name, ...]
    evidence: EvidenceItem
    model_call: ModelCallRecord

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if self.model_call.workspace_id != self.workspace_id:
            raise ValueError("news provenance workspace mismatch")
        if self.evidence.news_event is None or self.model_call.outcome != "success":
            raise ValueError("news records require extracted evidence and a successful model call")
        if self.evidence.ingested_at < self.evidence.news_event.first_seen_at:
            raise ValueError("structured evidence cannot predate article arrival")
        content_hash = news_record_hash(self.model_dump(mode="json"))
        if (
            self.evidence.content_hash != content_hash
            or self.evidence.evidence_id != "ev_" + content_hash[7:39]
            or self.event_id != "evt_" + content_hash[7:39]
        ):
            raise ValueError("news record content hash mismatch")
        return self


def news_record_hash(payload: dict[str, Any]) -> str:
    """Hash all frozen record fields except identifiers derived from that same hash."""
    content = {key: value for key, value in payload.items() if key != "event_id"}
    content["evidence"] = {
        key: value
        for key, value in payload["evidence"].items()
        if key not in {"evidence_id", "content_hash"}
    }
    serialized = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(serialized.encode()).hexdigest()


class NewsStatus(StrEnum):
    EXTRACTED = "extracted"
    DUPLICATE = "duplicate"
    QUARANTINED = "quarantined"
    UNAVAILABLE = "unavailable"
    IN_PROGRESS = "in_progress"
    CAPACITY = "capacity"


class NewsResult(DomainModel):
    status: NewsStatus
    reason_codes: tuple[Name, ...] = ()
    record: NewsRecord | None = None
    duplicate_of: Annotated[str | None, Field(pattern=r"^evt_[0-9a-f]{32}$")] = None
    model_call: ModelCallRecord | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if (self.status is NewsStatus.EXTRACTED) != (self.record is not None):
            raise ValueError("only extracted results carry evidence")
        if (self.status is NewsStatus.DUPLICATE) != (self.duplicate_of is not None):
            raise ValueError("only duplicates carry a prior event reference")
        return self
