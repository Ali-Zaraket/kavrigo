"""Local evidence-backed decisions and inert portfolio allocations. No execution tools."""

from kavrigo_runtime.analyzer import analysis_prompt
from kavrigo_runtime.contracts import (
    Allocation,
    AnalysisInput,
    Candidate,
    EvaluationRequest,
    EvaluationResult,
    EvaluationStatus,
    NetworkContext,
    NetworkContextProvider,
    PortfolioDecision,
    RuntimePolicy,
    RuntimeRegistration,
    ScannerPolicy,
)
from kavrigo_runtime.runtime import LocalAgentRuntime
from kavrigo_runtime.scanner import FrozenNetworkContexts, scan
from kavrigo_runtime.validation import network_hash, snapshot_hash

__all__ = [
    "Allocation",
    "AnalysisInput",
    "Candidate",
    "EvaluationRequest",
    "EvaluationResult",
    "EvaluationStatus",
    "FrozenNetworkContexts",
    "LocalAgentRuntime",
    "NetworkContext",
    "NetworkContextProvider",
    "PortfolioDecision",
    "RuntimePolicy",
    "RuntimeRegistration",
    "ScannerPolicy",
    "analysis_prompt",
    "network_hash",
    "scan",
    "snapshot_hash",
]
