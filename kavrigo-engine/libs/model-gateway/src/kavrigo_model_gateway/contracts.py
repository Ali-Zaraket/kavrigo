"""Internal contracts, not a transcription of any vendor's API (ADR 0010).

Prompt/schema registration and scope authorization belong to trusted application code. There
is no endpoint accepting caller-selected providers, system instructions, tools or schemas.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, model_validator

from kavrigo_domain import AgentVersion, DomainModel, ModelCallRecord, ModelProfile, TradingMode
from kavrigo_domain.identifiers import AgentId, AgentVersionId, DecisionId, WorkspaceId
from kavrigo_domain.money import ExactDecimal
from kavrigo_domain.numeric import DECIMAL_CONTEXT

Name = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Usd = Annotated[ExactDecimal, Field(ge=0, max_digits=24, decimal_places=12)]
Count = Annotated[int, Field(strict=True, ge=0, le=10_000_000)]


class FailureCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_ROUTE = "unsupported_route"
    MODEL_MISMATCH = "model_mismatch"
    SCHEMA_INVALID = "schema_invalid"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_REFUSED = "provider_refused"
    INCOMPLETE = "incomplete"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    USAGE_INVALID = "usage_invalid"
    COST_BUDGET = "cost_budget"
    RATE_BUDGET = "rate_budget"
    CALL_BUDGET = "call_budget"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    IN_PROGRESS = "in_progress"
    CAPACITY = "capacity"
    REPLAY_MISMATCH = "replay_mismatch"


class GatewayError(Exception):
    """Stable safe error code. Never wrap provider messages or validation input values."""

    def __init__(self, code: FailureCode, record: ModelCallRecord | None = None) -> None:
        self.code = code
        self.record = record
        super().__init__(code.value)


class CallScope(DomainModel):
    workspace_id: WorkspaceId
    agent_id: AgentId
    agent_version_id: AgentVersionId
    decision_id: DecisionId
    mode: Literal[TradingMode.PAPER, TradingMode.RESEARCH, TradingMode.BACKTEST]


class ModelRequest(DomainModel):
    scope: CallScope
    idempotency_key: Name
    profile: ModelProfile
    prompt_key: Name
    input_json: Annotated[str, Field(min_length=2, max_length=131_072, repr=False)]
    pinned_model_identifier: Annotated[str | None, Field(min_length=1, max_length=128)] = None

    @model_validator(mode="after")
    def _pin_backtest(self) -> Self:
        if self.scope.mode is TradingMode.BACKTEST and self.pinned_model_identifier is None:
            raise ValueError("backtest model calls require a pinned model identifier")
        return self


class EmbeddingRequest(ModelRequest):
    profile: Literal[ModelProfile.EMBED] = ModelProfile.EMBED


class EmbeddingInput(DomainModel):
    texts: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=8192)], ...],
        Field(min_length=1, max_length=32),
    ]


class EmbeddingOutput(DomainModel):
    # Vectors are non-monetary analytical values. Non-finite components are refused.
    vectors: Annotated[
        tuple[tuple[Annotated[float, Field(allow_inf_nan=False)], ...], ...],
        Field(min_length=1, max_length=32),
    ]


class Route(DomainModel):
    profile: ModelProfile
    provider: Name
    model_identifier: Annotated[str, Field(min_length=1, max_length=128)]
    pricing_version: Name
    input_usd_per_million: Usd
    output_usd_per_million: Usd
    max_input_tokens: Annotated[int, Field(strict=True, ge=1, le=1_000_000)]
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=32_768)]
    timeout_ms: Annotated[int, Field(strict=True, ge=1, le=600_000)]
    max_output_bytes: Annotated[int, Field(strict=True, ge=2, le=1_048_576)] = 131_072
    embedding_dimensions: Annotated[int | None, Field(strict=True, ge=1, le=4096)] = None
    retention: Literal["local_only"] = "local_only"

    @model_validator(mode="after")
    def _dimensions(self) -> Self:
        if (self.profile is ModelProfile.EMBED) != (self.embedding_dimensions is not None):
            raise ValueError("only embedding routes require embedding_dimensions")
        return self

    def cost_units(self, input_tokens: int, output_tokens: int) -> int:
        """Ceiling picodollars: bounded fixed-point accounting independent of global context."""
        numerator = (
            usd_units(self.input_usd_per_million) * input_tokens
            + usd_units(self.output_usd_per_million) * output_tokens
        )
        return (numerator + 999_999) // 1_000_000


class Usage(DomainModel):
    input_tokens: Count
    output_tokens: Count


class ProviderReply(DomainModel):
    """Untrusted until validated by the gateway, including model identity and usage."""

    model_identifier: Annotated[str, Field(min_length=1, max_length=128)]
    status: Literal["completed", "refused", "incomplete"]
    output_json: Annotated[str, Field(max_length=1_048_576, repr=False)] = ""
    usage: Usage | None = None


class ProviderRequest(DomainModel):
    """The provider sees only approved text/schema and limits, never workspace state or secrets."""

    model_identifier: str
    system_text: Annotated[str, Field(repr=False)]
    input_json: Annotated[str, Field(repr=False)]
    output_schema_json: str
    max_output_tokens: int


class ModelProvider(Protocol):
    name: str
    local_only: bool

    def input_token_bound(self, request: ProviderRequest) -> int:
        """Must bound ALL billable input, including system text and schema. No network I/O."""
        ...

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        """One attempt; no hidden SDK retries, tools or fallback. Honor cancellation."""
        ...


@dataclass(frozen=True)
class PromptDefinition:
    key: str
    profile: ModelProfile
    system_text: str
    input_type: type[DomainModel]
    output_type: type[DomainModel]


@dataclass(frozen=True)
class ModelResponse[T: DomainModel]:
    output: T
    record: ModelCallRecord
    replayed: bool = False


class ModelGateway(Protocol):
    async def structured[T: DomainModel](
        self, request: ModelRequest, output_type: type[T]
    ) -> ModelResponse[T]: ...

    async def embed(self, request: EmbeddingRequest) -> ModelResponse[EmbeddingOutput]: ...


class RecordedResponse(DomainModel):
    request_hash: Digest
    output_json: Annotated[str, Field(min_length=2, max_length=1_048_576, repr=False)]
    record: ModelCallRecord


class ScopeBudget(DomainModel):
    daily_usd: Usd
    calls_per_minute: Annotated[int, Field(strict=True, ge=1, le=100_000)]
    calls_per_day: Annotated[int, Field(strict=True, ge=1, le=1_000_000)]


class DecisionBudget(DomainModel):
    max_usd: Usd
    max_calls: Annotated[int, Field(strict=True, ge=1, le=64)]
    timeout_ms: Annotated[int, Field(strict=True, ge=1, le=600_000)]


class AgentAccess(DomainModel):
    """Loaded from authorized immutable configuration by the caller, not by model JSON."""

    workspace_id: WorkspaceId
    agent_id: AgentId
    agent_version_id: AgentVersionId
    profiles: tuple[ModelProfile, ...]
    prompt_keys: tuple[Name, ...]
    expected_prompt_hash: Digest | None = None
    daily_budget: ScopeBudget
    decision_budget: DecisionBudget
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=32_768)]

    @classmethod
    def from_version(
        cls,
        version: AgentVersion,
        *,
        daily_budget: ScopeBudget,
        prompt_keys: tuple[str, ...],
        max_calls: int,
    ) -> Self:
        """Use the immutable AgentSpec's cost/token/timeout limits; only service code grants
        this access after tenant authorization. Tool allowance does not grant a model tool.
        """
        policy = version.spec.model_policy
        return cls(
            workspace_id=version.workspace_id,
            agent_id=version.agent_id,
            agent_version_id=version.agent_version_id,
            profiles=(policy.profile,),
            prompt_keys=prompt_keys,
            expected_prompt_hash=version.prompt_hash,
            daily_budget=daily_budget,
            decision_budget=DecisionBudget(
                max_usd=policy.max_cost_per_decision_usd,
                max_calls=max_calls,
                timeout_ms=policy.timeout_seconds * 1000,
            ),
            max_output_tokens=policy.max_output_tokens,
        )


def usd_units(value: Decimal) -> int:
    with localcontext(DECIMAL_CONTEXT):
        return int(value * 10**12)


def units_usd(value: int) -> Decimal:
    with localcontext(DECIMAL_CONTEXT):
        return Decimal(value) / 10**12
