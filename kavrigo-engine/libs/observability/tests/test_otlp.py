"""Actual OTLP HTTP wire checks against a loopback receiver; no hosted account required."""

import base64
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


def test_service_bootstrap_exports_filtered_otlp_and_langfuse():
    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                (
                    self.path,
                    dict(self.headers),
                    self.rfile.read(int(self.headers["Content-Length"])),
                )
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    script = """
from opentelemetry import trace, metrics
from kavrigo_observability import telemetry_from_env
with telemetry_from_env("kavrigo-test"):
    tracer = trace.get_tracer("kavrigo.model_gateway")
    for replayed in (False, True):
        with tracer.start_as_current_span("model_gateway.call") as span:
            span.set_attributes({"langfuse.observation.type":"generation", "gen_ai.response.model":"mock-v1", "gen_ai.usage.input_tokens":3, "langfuse.observation.cost_details":'{"total":0.1}', "kavrigo.replayed":replayed, "gen_ai.prompt":"PRIVATE_SENTINEL", "kavrigo.workspace_id":"PRIVATE_SENTINEL"})
            span.add_event("PRIVATE_SENTINEL")
    with trace.get_tracer("kavrigo.api").start_as_current_span("control_plane.request"):
        metrics.get_meter("kavrigo.api").create_counter("kavrigo.http.requests").add(1, {"http.route":"/healthz", "workspace_id":"PRIVATE_SENTINEL"})
"""
    try:
        env = os.environ | {
            "KAVRIGO_TELEMETRY": "otlp",
            "KAVRIGO_OTLP_ENDPOINT": base,
            "KAVRIGO_LANGFUSE_ENDPOINT": base + "/api/public/otel/v1/traces",
            "LANGFUSE_PUBLIC_KEY": "fake-public",
            "LANGFUSE_SECRET_KEY": "fake-secret",
            "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=PRIVATE_SENTINEL",
        }
        process = subprocess.run(  # noqa: S603 - fixed local script; no dataset or user code
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert process.returncode == 0, process.stderr
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert {path for path, _, _ in received} == {
        "/v1/traces",
        "/v1/metrics",
        "/api/public/otel/v1/traces",
    }
    model_spans = []
    for path, headers, body in received:
        assert b"PRIVATE_SENTINEL" not in body
        assert "PRIVATE_SENTINEL" not in str(headers)
        if path == "/v1/metrics":
            message = ExportMetricsServiceRequest.FromString(body)
            assert message.resource_metrics
        else:
            message = ExportTraceServiceRequest.FromString(body)
            spans = [
                span
                for resource in message.resource_spans
                for scope in resource.scope_spans
                for span in scope.spans
            ]
            if path.startswith("/api/public"):
                assert (
                    headers["Authorization"]
                    == "Basic " + base64.b64encode(b"fake-public:fake-secret").decode()
                )
                assert headers["x-langfuse-ingestion-version"] == "4"
                model_spans.extend(spans)
            else:
                assert "Authorization" not in headers
    assert len(model_spans) == 2
    assert all(span.name == "model_gateway.call" for span in model_spans)
    attrs = [{a.key: a.value for a in span.attributes} for span in model_spans]
    assert sum("gen_ai.usage.input_tokens" in row for row in attrs) == 1
    assert sum("langfuse.observation.cost_details" in row for row in attrs) == 1
