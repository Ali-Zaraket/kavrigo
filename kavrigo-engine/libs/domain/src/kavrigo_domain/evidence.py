"""Evidence items: the frozen, attributable facts a decision is allowed to rest on.

``MASTER_BUILD_SPEC.md`` §1.2 requires every decision to answer what the agent knew, when it
knew it, where it came from, and how fresh it was. An ``EvidenceItem`` is that record.

Critically, evidence is the *only* form in which untrusted external content reaches a decision
agent (§14). Raw article text is sanitised and converted into structured items with provenance
and quality scores first; the agent never consumes arbitrary HTML.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from kavrigo_domain.base import DomainModel, UtcDatetime
from kavrigo_domain.identifiers import EvidenceId, InstrumentId

__all__ = [
    "EvidenceItem",
    "EvidenceKind",
    "NewsEvent",
    "NewsEventType",
    "Score",
    "SourceClass",
]

Score = Annotated[float, Field(ge=0.0, le=1.0)]
"""A bounded [0, 1] score. Scores are model or heuristic outputs, never money — floats are fine
here precisely because nothing is accounted for in them."""

SignedScore = Annotated[float, Field(ge=-1.0, le=1.0)]


class SourceClass(StrEnum):
    """Source classes from ``MASTER_BUILD_SPEC.md`` §42.

    Source class informs confidence. It never establishes truth: an official account can be
    compromised, and a wire service can be wrong.
    """

    OFFICIAL_PRIMARY = "official_primary"
    MAJOR_WIRE = "major_wire"
    SPECIALIST_PUBLICATION = "specialist_publication"
    PROJECT_SOCIAL = "project_social"
    UNVERIFIED_SOCIAL = "unverified_social"
    MARKET_DATA = "market_data"
    ONCHAIN_DATA = "onchain_data"
    DERIVED_FEATURE = "derived_feature"
    INTERNAL_MODEL = "internal_model"


class EvidenceKind(StrEnum):
    """What family of evidence this is, matching the signal families in §7."""

    PRICE_TECHNICAL = "price_technical"
    ORDER_FLOW = "order_flow"
    DERIVATIVES = "derivatives"
    ONCHAIN = "onchain"
    STABLECOIN = "stablecoin"
    ETF_FLOW = "etf_flow"
    TOKENOMICS = "tokenomics"
    DEFI = "defi"
    NETWORK_EVENT = "network_event"
    EXCHANGE_EVENT = "exchange_event"
    SECURITY_EVENT = "security_event"
    NEWS = "news"
    MACRO = "macro"
    REGULATION = "regulation"
    GEOPOLITICAL = "geopolitical"
    SOCIAL_ATTENTION = "social_attention"
    RELATIVE_STRENGTH = "relative_strength"


class NewsEventType(StrEnum):
    REGULATION = "regulation"
    ENFORCEMENT = "enforcement"
    LISTING = "listing"
    DELISTING = "delisting"
    PARTNERSHIP = "partnership"
    FUNDING = "funding"
    PROTOCOL_UPGRADE = "protocol_upgrade"
    OUTAGE = "outage"
    EXPLOIT = "exploit"
    GOVERNANCE = "governance"
    TOKEN_UNLOCK = "token_unlock"  # noqa: S105 - a scheduled supply event, not a credential
    MACRO_RELEASE = "macro_release"
    MARKET_STRUCTURE = "market_structure"
    OTHER = "other"


class NewsEvent(DomainModel):
    """A structured news event extracted from untrusted text (``MASTER_BUILD_SPEC.md`` §7.12).

    The extraction step is where an article stops being text and becomes data. Sentiment alone
    is close to useless; credibility, novelty, certainty and expected horizon are what make an
    event actionable or not.
    """

    event_type: NewsEventType
    assets: Annotated[list[str], Field(min_length=0, max_length=32)] = []
    importance: Score
    sentiment: SignedScore
    certainty: Score
    novelty: Score
    source_quality: Score
    expected_horizon: Annotated[str, Field(pattern=r"^(minutes|hours|days|weeks|unknown)$")]
    already_priced_in_likelihood: Score | None = None
    published_at: UtcDatetime
    first_seen_at: UtcDatetime
    primary_source_ref: Annotated[str | None, Field(default=None, max_length=512)] = None
    corroborating_source_refs: Annotated[list[str], Field(max_length=32)] = []

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.first_seen_at < self.published_at:
            raise ValueError("first_seen_at precedes published_at; check the feed's timestamps")
        return self


class EvidenceItem(DomainModel):
    """One immutable, attributable piece of evidence available to a decision.

    ``content_hash`` makes the item verifiable after the fact: a stored decision can be replayed
    against exactly the evidence that produced it.
    """

    evidence_id: EvidenceId
    kind: EvidenceKind
    source_class: SourceClass
    provider: Annotated[str, Field(min_length=1, max_length=64)]
    summary: Annotated[str, Field(min_length=1, max_length=2000)]
    """A short factual statement. Never raw fetched content, and never model instructions."""

    instruments: Annotated[list[InstrumentId], Field(max_length=64)] = []
    assets: Annotated[list[str], Field(max_length=64)] = []
    observed_at: UtcDatetime
    """When the underlying fact was true at the source."""
    ingested_at: UtcDatetime
    """When Kavrigo first recorded it. Freshness is measured against this and ``observed_at``."""

    source_ref: Annotated[str | None, Field(default=None, max_length=512)] = None
    """A URL or provider reference. Provenance only — a URL is never an instruction (§14)."""

    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    quality: Score
    confidence: Score
    is_contradictory_candidate: bool = False
    """Set when the item was surfaced specifically as counter-evidence to a thesis."""

    news_event: NewsEvent | None = None
    injection_signals: Annotated[list[str], Field(max_length=32)] = []
    """Suspicious-instruction patterns detected during sanitisation. Recorded and ignored, never
    acted upon (``MASTER_BUILD_SPEC.md`` §14)."""

    license_ref: Annotated[str | None, Field(default=None, max_length=128)] = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.ingested_at < self.observed_at:
            raise ValueError("ingested_at precedes observed_at")
        if self.news_event is not None and self.kind is not EvidenceKind.NEWS:
            raise ValueError("news_event may only be attached to NEWS evidence")
        return self
