import json

from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from structlog.testing import capture_logs

from kavrigo_api.app import create_app
from kavrigo_api.settings import Settings


def test_http_outcomes_exclude_payload_paths_and_exceptions():
    exporter = InMemorySpanExporter()
    traces = TracerProvider()
    traces.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    meters = MeterProvider(metric_readers=[reader])
    app = create_app(
        Settings(), tracer=traces.get_tracer("kavrigo.api"), meter=meters.get_meter("kavrigo.api")
    )

    @app.get("/_test/{item}")
    async def fail(item: str):
        raise RuntimeError("sensitive-exception-sentinel")

    try:
        with capture_logs() as logs, TestClient(app, raise_server_exceptions=False) as client:
            assert client.get("/healthz").status_code == 200
            response = client.get(
                "/_test/sensitive-path-sentinel?token=sensitive-query-sentinel",
                headers={
                    "authorization": "Bearer sensitive-header-sentinel",
                    "x-request-id": "unsafe id " * 20,
                },
            )
            assert response.status_code == 500
            assert len(response.json()["request_id"]) == 32
            assert client.get("/unmatched-sensitive-sentinel/other").status_code == 404
        spans = exporter.get_finished_spans()
        assert len(spans) == 3
        assert spans[1].attributes["http.route"] == "/_test/{item}"
        assert spans[1].status.status_code.name == "ERROR"
        assert spans[2].attributes["http.route"] == "unmatched"
        assert all(not span.events for span in spans)
        data = reader.get_metrics_data()
        assert data is not None
        text = json.dumps(logs) + data.to_json() + "".join(span.to_json() for span in spans)
        for forbidden in (
            "sensitive-exception-sentinel",
            "sensitive-path-sentinel",
            "sensitive-query-sentinel",
            "sensitive-header-sentinel",
            "unmatched-sensitive-sentinel",
        ):
            assert forbidden not in text
    finally:
        meters.shutdown()
        traces.shutdown()
