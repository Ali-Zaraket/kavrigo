"""``AgentSpec`` and ``AgentVersion`` (``MASTER_BUILD_SPEC.md`` §9, §38).

An agent is a declarative, inspectable specification — not user code (ADR 0018). Natural
language *compiles into* this structure, and the structure is authoritative: what the user
reviews and approves is the spec, not the conversation that produced it.

Editing an agent creates a new ``AgentVersion``. It never mutates the configuration that
produced historical decisions (``MASTER_BUILD_SPEC.md`` §3).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from kavrigo_domain.base import DomainModel, UtcDatetime
from kavrigo_domain.identifiers import (
    AgentId,
    AgentVersionId,
    InstrumentClass,
    InstrumentId,
    WorkspaceId,
)
from kavrigo_domain.money import ExactDecimal

__all__ = [
    "AgentSpec",
    "AgentVersion",
    "AnalysisConfig",
    "ApprovalStatus",
    "AuthorKind",
    "DataPack",
    "EvidenceRequirements",
    "ModelPolicy",
    "ModelProfile",
    "PromotionStage",
    "ScheduleConfig",
    "TradingMode",
    "UniverseConfig",
]


class TradingMode(StrEnum):
    """The four product modes (``MASTER_BUILD_SPEC.md`` §5).

    ``LIVE`` exists in the type system so that code can reason about it, and is refused at
    runtime unless the live gate is open (ADR 0001).
    """

    RESEARCH = "research"
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"

    @property
    def touches_real_funds(self) -> bool:
        return self is TradingMode.LIVE


class DataPack(StrEnum):
    """Explicitly enabled data families (``MASTER_BUILD_SPEC.md`` §7).

    Packs are opt-in per agent because they carry both cost and licence entitlement (§8.3).
    """

    MARKET_MICROSTRUCTURE = "market_microstructure"
    PRICE_TECHNICAL = "price_technical"
    DERIVATIVES = "derivatives"
    ONCHAIN_CORE = "onchain_core"
    STABLECOINS = "stablecoins"
    ETF_FLOWS = "etf_flows"
    TOKENOMICS = "tokenomics"
    DEFI = "defi"
    NEWS = "news"
    MACRO = "macro"
    SECURITY_EVENTS = "security_events"
    SOCIAL_ATTENTION = "social_attention"
    RELATIVE_STRENGTH = "relative_strength"


class ModelProfile(StrEnum):
    """Routing profiles, not model names (``MASTER_BUILD_SPEC.md`` §13.5).

    Product behaviour must not be hard-coded to a current model name; the gateway resolves a
    profile to a concrete model, and the resolved identifier is recorded on the decision.
    """

    EXTRACT_FAST = "extract_fast"
    CLASSIFY_FAST = "classify_fast"
    REASON_BALANCED = "reason_balanced"
    REASON_DEEP = "reason_deep"
    EMBED = "embed"


class PromotionStage(StrEnum):
    """Promotion pipeline stages (``MASTER_BUILD_SPEC.md`` §12.6).

    A failed gate produces a new version; it never rewrites history.
    """

    DRAFT = "draft"
    HISTORICAL_BACKTEST = "historical_backtest"
    OUT_OF_SAMPLE = "out_of_sample"
    PAPER_CANDIDATE = "paper_candidate"
    PAPER_OBSERVATION = "paper_observation"
    LIVE_ELIGIBLE = "live_eligible"
    LIVE_LIMITED = "live_limited"
    LIVE_EXPANDED = "live_expanded"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class AuthorKind(StrEnum):
    """Whether a version's changes were written by a human or generated (§38)."""

    HUMAN = "human"
    AI_ASSISTED = "ai_assisted"
    AI_GENERATED = "ai_generated"


class UniverseConfig(DomainModel):
    instruments: Annotated[list[InstrumentId], Field(min_length=1, max_length=256)]
    market_type: InstrumentClass = InstrumentClass.SPOT

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.market_type is not InstrumentClass.SPOT:
            raise ValueError(
                "V1 is spot-only (ADR 0002); derivatives data is available as a data pack but "
                "is not executable"
            )
        for instrument in self.instruments:
            if instrument.instrument_class is not InstrumentClass.SPOT:
                raise ValueError(f"{instrument.value} is not a spot instrument")
        return self


class ScheduleConfig(DomainModel):
    decision_interval_seconds: Annotated[int, Field(ge=60, le=86_400)]
    """Minimum 60s. V1 is explicitly not a high-frequency platform (§1.3)."""

    event_triggers: Annotated[list[str], Field(max_length=32)] = []
    max_decisions_per_day: Annotated[int, Field(ge=1, le=1440)] = 96
    """A hard cost and behaviour bound (``MASTER_BUILD_SPEC.md`` §46)."""


class AnalysisConfig(DomainModel):
    market_scanner: bool = True
    network_context: bool = True
    asset_analyzer: bool = True
    portfolio_layer: bool = True
    horizons_minutes: Annotated[list[int], Field(min_length=1, max_length=8)] = [60]
    allow_abstain: bool = True

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.allow_abstain:
            # "Always trade" behaviour is prohibited (AGENTS.md domain rule 15). Abstention is a
            # successful outcome, and an agent that cannot abstain will trade on noise.
            raise ValueError("abstention cannot be disabled; NO_TRADE is a valid outcome")
        if not self.portfolio_layer:
            raise ValueError(
                "the portfolio layer is mandatory: correlated per-asset decisions are one trade"
            )
        return self


class ModelPolicy(DomainModel):
    profile: ModelProfile = ModelProfile.REASON_BALANCED
    max_cost_per_decision_usd: ExactDecimal
    max_tool_calls: Annotated[int, Field(ge=0, le=64)] = 12
    max_output_tokens: Annotated[int, Field(ge=64, le=32_768)] = 4096
    timeout_seconds: Annotated[int, Field(ge=1, le=600)] = 60

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.max_cost_per_decision_usd <= 0:
            raise ValueError("max_cost_per_decision_usd must be positive")
        return self


class EvidenceRequirements(DomainModel):
    """What an agent must have before it is permitted to act (``MASTER_BUILD_SPEC.md`` §9)."""

    min_source_quality: Annotated[float, Field(ge=0.0, le=1.0)] = 0.65
    require_timestamps: bool = True
    require_contradicting_evidence: bool = True
    """Forces the agent to look for counter-evidence rather than confirming a thesis."""

    min_evidence_items: Annotated[int, Field(ge=1, le=64)] = 2


class AgentSpec(DomainModel):
    """The declarative agent specification a user reviews and approves."""

    api_version: Annotated[str, Field(pattern=r"^agents\.kavrigo/v\d+$")] = "agents.kavrigo/v1"
    kind: Annotated[str, Field(pattern=r"^TradingAgent$")] = "TradingAgent"
    name: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")]
    description: Annotated[str, Field(max_length=1000)] = ""
    mode: TradingMode = TradingMode.PAPER
    universe: UniverseConfig
    schedule: ScheduleConfig
    data_packs: Annotated[list[DataPack], Field(min_length=1, max_length=16)]
    analysis: AnalysisConfig = AnalysisConfig()
    model_policy: ModelPolicy
    evidence: EvidenceRequirements = EvidenceRequirements()
    risk_policy_ref: Annotated[str, Field(pattern=r"^rp_[0-9a-f]{32}$")]
    execution_policy_ref: Annotated[str, Field(pattern=r"^ep_[0-9a-f]{32}$")]

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.mode is TradingMode.LIVE:
            # Defence in depth: the runtime gate is authoritative, but a spec should not be
            # constructible in live mode by accident during the paper-only phase (ADR 0001).
            raise ValueError(
                "live mode cannot be set on an AgentSpec while LIVE_TRADING_ENABLED is false; "
                "promotion to live is a gated platform operation, not a spec field"
            )
        if DataPack.NEWS in self.data_packs and not self.evidence.require_timestamps:
            raise ValueError("news data requires point-in-time timestamps on evidence")
        return self


class AgentVersion(DomainModel):
    """An immutable, promotable version of an agent (``MASTER_BUILD_SPEC.md`` §38).

    Any change to the prompt, model profile, data pack, feature version, risk policy, execution
    policy, universe or schedule creates a new version. Runs reference the version, never the
    agent, so historical decisions stay explicable.
    """

    agent_version_id: AgentVersionId
    agent_id: AgentId
    workspace_id: WorkspaceId
    version: Annotated[int, Field(ge=1)]
    spec: AgentSpec
    spec_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    prompt_version_id: Annotated[str, Field(pattern=r"^pv_[0-9a-f]{32}$")]
    prompt_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    feature_set_version: Annotated[str, Field(pattern=r"^v\d+(\.\d+)*$")]
    created_at: UtcDatetime
    created_by: Annotated[str, Field(min_length=1, max_length=128)]
    author_kind: AuthorKind = AuthorKind.HUMAN
    change_summary: Annotated[str, Field(max_length=2000)] = ""
    stage: PromotionStage = PromotionStage.DRAFT
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approved_environments: Annotated[list[str], Field(max_length=8)] = []

    def is_approved_for(self, environment: str) -> bool:
        """Whether this version may run in ``environment``.

        The risk engine rejects any intent from a version not approved for the current
        environment (``MASTER_BUILD_SPEC.md`` §11.1).
        """
        return (
            self.approval_status is ApprovalStatus.APPROVED
            and environment in self.approved_environments
        )
