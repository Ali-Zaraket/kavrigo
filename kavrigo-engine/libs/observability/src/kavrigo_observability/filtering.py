"""Export only registered application spans and metadata, never arbitrary SDK content."""

from collections.abc import Sequence

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import SpanContext, Status

SPAN_NAMES = {
    "control_plane.request",
    "model_gateway.call",
    "agent.evaluate",
    "news.extract",
    "risk.evaluate",
    "paper.commit",
    "account.command",
    "workflow.stage",
}
SCOPES = {
    "kavrigo.api",
    "kavrigo.model_gateway",
    "kavrigo.runtime",
    "kavrigo.news",
    "kavrigo.risk",
    "kavrigo.paper",
    "kavrigo.durable.account",
    "kavrigo.workflows",
}
ATTRIBUTES = {
    "http.request.method",
    "http.route",
    "http.response.status_code",
    "langfuse.observation.type",
    "langfuse.observation.cost_details",
    "gen_ai.response.model",
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens",
    "kavrigo.model.profile",
    "kavrigo.model.outcome",
    "kavrigo.prompt_hash",
    "kavrigo.cost_usd",
    "kavrigo.cost_is_reservation",
    "kavrigo.replayed",
    "runtime.status",
    "runtime.replayed",
    "news.status",
    "risk.decision",
    "risk.replayed",
}


def clean_context(context: SpanContext | None) -> SpanContext | None:
    if context is None:
        return None
    return SpanContext(context.trace_id, context.span_id, context.is_remote, context.trace_flags)


class SafeSpanExporter(SpanExporter):
    def __init__(self, target: SpanExporter, resource: Resource, *, model_only: bool = False):
        self.target, self.resource, self.model_only = target, resource, model_only

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        clean = []
        for span in spans:
            scope = span.instrumentation_scope
            if span.name not in SPAN_NAMES or scope is None or scope.name not in SCOPES:
                continue
            if self.model_only and span.name != "model_gateway.call":
                continue
            attrs = {k: v for k, v in (span.attributes or {}).items() if k in ATTRIBUTES}
            if attrs.get("kavrigo.cost_is_reservation") is True:
                attrs = {
                    k: v
                    for k, v in attrs.items()
                    if not k.startswith("gen_ai.usage.")
                    and k != "langfuse.observation.cost_details"
                }
            if attrs.get("kavrigo.replayed") is True:
                # Langfuse can derive cost from model/usage, so remove all generation fields.
                attrs = {
                    k: v
                    for k, v in attrs.items()
                    if not k.startswith("gen_ai.") and k != "langfuse.observation.cost_details"
                }
                attrs["langfuse.observation.type"] = "span"
            clean.append(
                ReadableSpan(
                    name=span.name,
                    context=clean_context(span.context),
                    parent=clean_context(span.parent),
                    resource=self.resource,
                    attributes=attrs,
                    events=(),
                    links=(),
                    kind=span.kind,
                    status=Status(span.status.status_code),
                    start_time=span.start_time,
                    end_time=span.end_time,
                    instrumentation_scope=InstrumentationScope(scope.name),
                )
            )
        if not clean:
            return SpanExportResult.SUCCESS
        try:
            return self.target.export(clean)
        except Exception:
            # Exporters are diagnostics; an exporter exception must never change command outcome.
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self.target.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.target.force_flush(timeout_millis)
