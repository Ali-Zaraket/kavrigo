import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode
from pydantic import ValidationError

from kavrigo_observability.bootstrap import metric_views
from kavrigo_observability.config import TelemetryConfig
from kavrigo_observability.filtering import SafeSpanExporter


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.test/",
        "https://user:secret@example.test/",
        "file:///tmp/output",
        "https://example.test/?key=secret",
    ],
)
def test_bad_endpoint_refused(url):
    with pytest.raises(ValidationError):
        TelemetryConfig(service="kavrigo-api", mode="otlp", collector=url)


def test_partial_or_disabled_langfuse_refused():
    with pytest.raises(ValidationError):
        TelemetryConfig(service="kavrigo-api", langfuse_secret_key="secret")
    with pytest.raises(ValidationError):
        TelemetryConfig(service="kavrigo-api", mode="otlp")
    assert TelemetryConfig(service="kavrigo-api").mode == "off"


def test_export_filter_removes_content_and_replayed_cost():
    sink = InMemorySpanExporter()
    resource = Resource({"service.name": "kavrigo-test"})
    provider = TracerProvider(resource=Resource({"secret": "sentinel"}))
    provider.add_span_processor(
        SimpleSpanProcessor(SafeSpanExporter(sink, resource, model_only=True))
    )
    tracer = provider.get_tracer("kavrigo.model_gateway", "sensitive-version")
    try:
        for replay in (False, True):
            with tracer.start_as_current_span("model_gateway.call") as span:
                span.set_attributes(
                    {
                        "kavrigo.workspace_id": "sentinel",
                        "gen_ai.prompt": "sentinel",
                        "langfuse.observation.type": "generation",
                        "gen_ai.response.model": "mock-v1",
                        "gen_ai.usage.input_tokens": 3,
                        "kavrigo.replayed": replay,
                        "langfuse.observation.cost_details": '{"total":0.1}',
                    }
                )
                span.add_event("sentinel", {"exception.message": "sentinel"})
                span.set_status(Status(StatusCode.ERROR, "sentinel"))
            with tracer.start_as_current_span("arbitrary-sensitive-name"):
                pass
        with provider.get_tracer("kavrigo.api").start_as_current_span("control_plane.request"):
            pass
        exported = sink.get_finished_spans()
        assert len(exported) == 2
        text = "".join(span.to_json() for span in exported)
        assert "sentinel" not in text
        assert "sensitive-version" not in text
        assert exported[0].attributes["langfuse.observation.cost_details"] == '{"total":0.1}'
        assert exported[1].attributes["langfuse.observation.type"] == "span"
        assert "gen_ai.usage.input_tokens" not in exported[1].attributes
        assert "gen_ai.response.model" not in exported[1].attributes
        assert "langfuse.observation.cost_details" not in exported[1].attributes
    finally:
        provider.shutdown()


def test_metrics_drop_unknown_instruments_and_tenant_dimensions():
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], views=metric_views())
    try:
        meter = provider.get_meter("kavrigo.api")
        meter.create_counter("private.metric").add(1, {"secret": "sentinel"})
        meter.create_counter("kavrigo.http.requests").add(
            1,
            {
                "workspace_id": "sentinel",
                "http.route": "/healthz",
                "http.response.status_code": 200,
            },
        )
        data = reader.get_metrics_data()
        assert data is not None
        text = data.to_json()
        assert "sentinel" not in text
        assert "private.metric" not in text
        assert "kavrigo.http.requests" in text
    finally:
        provider.shutdown()


def test_export_failure_is_diagnostic_only():
    class Broken(InMemorySpanExporter):
        def export(self, spans):
            raise RuntimeError("private-export-error")

    provider = TracerProvider()
    sink = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(sink))
    with provider.get_tracer("kavrigo.api").start_as_current_span("control_plane.request"):
        pass
    assert (
        SafeSpanExporter(Broken(), Resource({})).export(sink.get_finished_spans())
        is SpanExportResult.FAILURE
    )
    provider.shutdown()
