"""Kavrigo's provider-neutral model boundary (ADR 0010)."""

from kavrigo_model_gateway.budget import LocalBudgetLedger
from kavrigo_model_gateway.contracts import (
    AgentAccess,
    CallScope,
    DecisionBudget,
    EmbeddingInput,
    EmbeddingOutput,
    EmbeddingRequest,
    FailureCode,
    GatewayError,
    ModelGateway,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    PromptDefinition,
    ProviderReply,
    ProviderRequest,
    RecordedResponse,
    Route,
    ScopeBudget,
    Usage,
)
from kavrigo_model_gateway.gateway import LocalModelGateway, registered_prompt_hash
from kavrigo_model_gateway.mock import MockProvider

__all__ = [
    "AgentAccess",
    "CallScope",
    "DecisionBudget",
    "EmbeddingInput",
    "EmbeddingOutput",
    "EmbeddingRequest",
    "FailureCode",
    "GatewayError",
    "LocalBudgetLedger",
    "LocalModelGateway",
    "MockProvider",
    "ModelGateway",
    "ModelProvider",
    "ModelRequest",
    "ModelResponse",
    "PromptDefinition",
    "ProviderReply",
    "ProviderRequest",
    "RecordedResponse",
    "Route",
    "ScopeBudget",
    "Usage",
    "registered_prompt_hash",
]
