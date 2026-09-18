"""Versioned, closed evaluation and result contracts."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from kavrigo_domain import DomainModel
from kavrigo_domain.evidence import NewsEventType
from kavrigo_model_gateway.contracts import Digest, Name
from kavrigo_news import NewsStatus


class NewsCase(DomainModel):
    kind: Literal["news"]
    case_id: Name
    category: Literal["extraction", "injection"]
    title: str = "Synthetic protocol notice"
    body_html: str = Field(min_length=1, max_length=65536, repr=False)
    model_reply: str = Field(max_length=131072, repr=False)
    published_seconds_ago: int | None = 300
    provider_failure: bool = False
    expected_status: NewsStatus
    expected_reason: Name | None = None
    expected_calls: Literal[0, 1]
    expected_event: NewsEventType | None = None
    expected_assets: tuple[str, ...] = ()
    expected_quote: str | None = None


class DecisionCase(DomainModel):
    kind: Literal["decision"]
    case_id: Name
    category: Literal["decision"] = "decision"
    input_json: str = '{"facts":["Synthetic evidence is inconclusive."]}'
    model_reply: str = Field(max_length=131072, repr=False)
    provider_failure: bool = False
    expected_status: Literal["success", "schema_invalid", "invalid_input", "provider_unavailable"]
    expected_calls: Literal[0, 1] = 1
    expected_action: str | None = None
    expected_amount: str | None = None


Case = Annotated[NewsCase | DecisionCase, Field(discriminator="kind")]


class GoldenDataset(DomainModel):
    version: Literal["kavrigo-golden-v1"]
    provenance: Literal["authored-synthetic-no-provider-content"]
    cases: tuple[Case, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Evaluation IDs must be unique")
        return self


class CaseResult(DomainModel):
    case_id: Name
    category: str
    observed_status: str
    checks: dict[str, bool]
    passed: bool


class EvaluationReport(DomainModel):
    version: Literal["kavrigo-eval-report-v1"] = "kavrigo-eval-report-v1"
    dataset_hash: Digest
    code_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    working_tree_dirty: bool
    provider: Literal["scripted-mock-v1"] = "scripted-mock-v1"
    scientific_scope: Literal["boundary-regression-only"] = "boundary-regression-only"
    clock: Literal["2026-09-08T12:00:00Z"] = "2026-09-08T12:00:00Z"
    random_seed: Literal[0] = 0
    prompt_hashes: dict[str, Digest]
    schema_hashes: dict[str, Digest]
    dependency_versions: dict[str, str]
    results: tuple[CaseResult, ...]
    passed: bool
