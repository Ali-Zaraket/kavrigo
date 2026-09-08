"""Kavrigo domain contracts.

These types are the shared vocabulary between the control plane, the engine and (eventually) the
isolated execution boundary. They encode the non-negotiable domain rules from ``AGENTS.md``
structurally rather than by convention:

* money and quantity are exact decimals with units (``money``);
* instruments are explicit, never bare tickers (``identifiers``);
* a model output is a *proposal*, never an order (``decision``);
* only the deterministic risk engine produces an ``ApprovedOrderIntent`` (``risk``, ``orders``);
* ``UNKNOWN`` and ``NO_TRADE`` are valid successful outcomes (``decision``);
* data freshness is a risk input (``snapshot``, ``risk``);
* every run references immutable versions (``agent``, ``audit``).

Everything here is frozen and rejects unknown fields, so an unvalidated provider payload or
model response cannot enter the domain unnoticed.
"""

from __future__ import annotations

from kavrigo_domain.agent import (
    AgentSpec,
    AgentVersion,
    AnalysisConfig,
    ApprovalStatus,
    AuthorKind,
    DataPack,
    EvidenceRequirements,
    ModelPolicy,
    ModelProfile,
    PromotionStage,
    ScheduleConfig,
    TradingMode,
    UniverseConfig,
)
from kavrigo_domain.audit import AuditAction, AuditRecord
from kavrigo_domain.base import DomainModel, UtcDatetime, utc_now
from kavrigo_domain.decision import (
    AgentDecision,
    DecisionProposal,
    DecisionState,
    ModelCallRecord,
    Prediction,
    ProposedAction,
    SignalScores,
)
from kavrigo_domain.events import EventEnvelope, EventSource, SourceKind, TenantScope
from kavrigo_domain.evidence import (
    EvidenceItem,
    EvidenceKind,
    NewsEvent,
    NewsEventType,
    SourceClass,
)
from kavrigo_domain.hashing import canonical_json, content_hash, model_hash
from kavrigo_domain.identifiers import (
    IdPrefix,
    InstrumentClass,
    InstrumentId,
    new_id,
)
from kavrigo_domain.market import AggressorSide, BookTicker, Candle, MarketTrade
from kavrigo_domain.money import AssetCode, ExactDecimal, Money, Price, Quantity
from kavrigo_domain.numeric import (
    DECIMAL_CONTEXT,
    FEATURE_CONTEXT,
    mean,
    safe_divide,
    stdev,
    to_bps,
)
from kavrigo_domain.orders import (
    ApprovedOrderIntent,
    Fill,
    LiquidityFlag,
    Order,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from kavrigo_domain.portfolio import PortfolioSnapshot, Position
from kavrigo_domain.risk import (
    EventRiskPolicy,
    FreshnessPolicy,
    RiskDecision,
    RiskEvaluation,
    RiskLimits,
    RiskPolicy,
    RiskReasonCode,
    RiskScope,
)
from kavrigo_domain.snapshot import (
    DataFamily,
    DataQuality,
    FeatureVector,
    FreshnessReport,
    MarketRegime,
    MarketSnapshot,
)

__version__ = "0.1.0"

__all__ = [
    "DECIMAL_CONTEXT",
    "FEATURE_CONTEXT",
    "AgentDecision",
    "AgentSpec",
    "AgentVersion",
    "AggressorSide",
    "AnalysisConfig",
    "ApprovalStatus",
    "ApprovedOrderIntent",
    "AssetCode",
    "AuditAction",
    "AuditRecord",
    "AuthorKind",
    "BookTicker",
    "Candle",
    "DataFamily",
    "DataPack",
    "DataQuality",
    "DecisionProposal",
    "DecisionState",
    "DomainModel",
    "EventEnvelope",
    "EventRiskPolicy",
    "EventSource",
    "EvidenceItem",
    "EvidenceKind",
    "EvidenceRequirements",
    "ExactDecimal",
    "FeatureVector",
    "Fill",
    "FreshnessPolicy",
    "FreshnessReport",
    "IdPrefix",
    "InstrumentClass",
    "InstrumentId",
    "LiquidityFlag",
    "MarketRegime",
    "MarketSnapshot",
    "MarketTrade",
    "ModelCallRecord",
    "ModelPolicy",
    "ModelProfile",
    "Money",
    "NewsEvent",
    "NewsEventType",
    "Order",
    "OrderIntent",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PortfolioSnapshot",
    "Position",
    "Prediction",
    "Price",
    "PromotionStage",
    "ProposedAction",
    "Quantity",
    "RiskDecision",
    "RiskEvaluation",
    "RiskLimits",
    "RiskPolicy",
    "RiskReasonCode",
    "RiskScope",
    "ScheduleConfig",
    "SignalScores",
    "SourceClass",
    "SourceKind",
    "TenantScope",
    "TimeInForce",
    "TradingMode",
    "UniverseConfig",
    "UtcDatetime",
    "__version__",
    "canonical_json",
    "content_hash",
    "mean",
    "model_hash",
    "new_id",
    "safe_divide",
    "stdev",
    "to_bps",
    "utc_now",
]
