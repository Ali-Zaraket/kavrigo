from __future__ import annotations

import json

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from structlog.testing import capture_logs

from kavrigo_domain import DecisionProposal
from kavrigo_model_gateway import GatewayError
from kavrigo_model_gateway.telemetry import GatewayTelemetry


@pytest.fixture
def telemetry():
    traces = TracerProvider()
    exporter = InMemorySpanExporter()
    traces.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    meters = MeterProvider(metric_readers=[reader])
    yield (
        GatewayTelemetry(traces.get_tracer("gateway-test"), meters.get_meter("gateway-test")),
        exporter,
        reader,
    )
    traces.shutdown()
    meters.shutdown()


async def test_traces_and_metrics_are_content_free(build_gateway, request_model, telemetry):
    observer, exporter, reader = telemetry
    gateway, _ = build_gateway(telemetry=observer)
    with capture_logs() as logs:
        result = await gateway.structured(request_model, DecisionProposal)
        await gateway.structured(request_model, DecisionProposal)
    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    attrs = spans[0].attributes
    assert attrs["langfuse.observation.type"] == "generation"
    assert attrs["gen_ai.response.model"] == result.record.resolved_model_identifier
    assert result.record.trace_id == f"{spans[0].context.trace_id:032x}"
    assert spans[1].attributes["kavrigo.replayed"] is True
    assert "No reliable evidence" not in json.dumps([dict(s.attributes) for s in spans])
    assert "insufficient_evidence" not in json.dumps(logs)
    data = reader.get_metrics_data()
    metrics = {
        m.name: m
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for m in scope.metrics
    }
    assert sum(p.value for p in metrics["kavrigo.model.calls"].data.data_points) == 2
    assert (
        sum(p.value for p in metrics["kavrigo.model.tokens"].data.data_points)
        == result.record.input_tokens + result.record.output_tokens
    )
    # Workspace/agent IDs are trace/log context, never high-cardinality metric labels.
    for metric in metrics.values():
        assert all("workspace_id" not in p.attributes for p in metric.data.data_points)


@pytest.mark.parametrize("provider_error", [False, True])
async def test_failure_telemetry_never_exports_payload_or_exception(
    build_gateway, request_model, telemetry, provider_error
):
    observer, exporter, _ = telemetry
    payload = "api_key=private-sentinel"
    outputs = [RuntimeError(payload)] if provider_error else ['{"unexpected":"' + payload + '"}']
    gateway, _ = build_gateway(outputs=outputs, telemetry=observer)
    with capture_logs() as logs, pytest.raises(GatewayError):
        await gateway.structured(request_model, DecisionProposal)
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code.name == "ERROR"
    assert not span.events
    assert "private-sentinel" not in json.dumps(dict(span.attributes))
    assert "private-sentinel" not in json.dumps(logs)
