"""Content-free OpenTelemetry/Langfuse hooks (ADR 0011), never the audit ledger.

Attribute mapping verified 2026-09-08:
https://langfuse.com/integrations/native/opentelemetry
https://opentelemetry.io/docs/languages/python/instrumentation/
Exporters are injected by the service. This library reads no keys or environment variables.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import structlog
from opentelemetry import metrics, trace
from opentelemetry.trace import Span, StatusCode

from kavrigo_domain import ModelCallRecord
from kavrigo_model_gateway.contracts import FailureCode, ModelRequest

_log = structlog.get_logger("kavrigo.model_gateway")


class GatewayTelemetry:
    def __init__(
        self, tracer: trace.Tracer | None = None, meter: metrics.Meter | None = None
    ) -> None:
        self._tracer = tracer or trace.get_tracer("kavrigo.model_gateway", "0.1.0")
        meter = meter or metrics.get_meter("kavrigo.model_gateway", "0.1.0")
        self._calls = meter.create_counter("kavrigo.model.calls", unit="{call}")
        self._latency = meter.create_histogram("kavrigo.model.duration", unit="ms")
        self._tokens = meter.create_counter("kavrigo.model.tokens", unit="{token}")

    @contextmanager
    def span(self, request: ModelRequest) -> Iterator[Span]:
        # Automatic exception recording would capture Pydantic inputs/provider bodies.
        with self._tracer.start_as_current_span(
            "model_gateway.call", record_exception=False, set_status_on_exception=False
        ) as span:
            span.set_attribute("kavrigo.workspace_id", request.scope.workspace_id)
            span.set_attribute("kavrigo.agent_id", request.scope.agent_id)
            span.set_attribute("kavrigo.decision_id", request.scope.decision_id)
            span.set_attribute("kavrigo.model.profile", request.profile.value)
            span.set_attribute(
                "langfuse.observation.type",
                "embedding" if request.profile.value == "embed" else "generation",
            )
            yield span

    def completed(self, span: Span, record: ModelCallRecord, *, replayed: bool = False) -> None:
        labels: dict[str, str | bool] = {
            "profile": record.profile,
            "outcome": record.outcome,
            "replayed": replayed,
        }
        span.set_attribute("gen_ai.response.model", record.resolved_model_identifier)
        span.set_attribute("kavrigo.model_call_id", record.model_call_id)
        span.set_attribute("kavrigo.prompt_hash", record.prompt_hash)
        span.set_attribute("kavrigo.model.outcome", record.outcome)
        span.set_attribute("kavrigo.cost_usd", str(record.cost.amount))
        span.set_attribute("kavrigo.cost_is_reservation", record.cost_is_reservation)
        span.set_attribute("kavrigo.replayed", replayed)
        if record.usage_known:
            span.set_attribute("gen_ai.usage.input_tokens", record.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", record.output_tokens)
        if record.outcome != "success":
            span.set_status(StatusCode.ERROR, record.outcome)
        self._calls.add(1, labels)
        if not replayed:
            self._latency.record(record.latency_ms, labels)
            if record.usage_known:
                self._tokens.add(record.input_tokens + record.output_tokens, labels)
        _log.info(
            "model_call_finished",
            workspace_id=record.workspace_id,
            agent_id=record.agent_id,
            model_call_id=record.model_call_id,
            profile=record.profile,
            outcome=record.outcome,
            cost_usd=str(record.cost.amount),
            usage_known=record.usage_known,
            latency_ms=record.latency_ms,
            replayed=replayed,
        )

    def rejected(self, span: Span, code: FailureCode) -> None:
        span.set_status(StatusCode.ERROR, code.value)
        span.set_attribute("kavrigo.model.outcome", code.value)
        self._calls.add(1, {"outcome": code.value})
        _log.info("model_call_rejected", reason_code=code.value)
