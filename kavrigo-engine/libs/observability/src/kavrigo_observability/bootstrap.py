"""Configure providers once, at process entry; tests inject isolated providers instead."""

import base64
import os
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import AlwaysOffExemplarFilter, MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import DropAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SpanExporter
from pydantic import SecretStr

from kavrigo_observability.config import TelemetryConfig
from kavrigo_observability.filtering import SafeSpanExporter

METRICS = {
    "kavrigo.http.requests": {"http.request.method", "http.route", "http.response.status_code"},
    "kavrigo.http.duration": {"http.request.method", "http.route", "http.response.status_code"},
    "kavrigo.model.calls": {"profile", "outcome", "replayed"},
    "kavrigo.model.duration": {"profile", "outcome", "replayed"},
    "kavrigo.model.tokens": {"profile", "outcome", "replayed"},
    "kavrigo.news.results": {"news.status"},
    "kavrigo.news.source_age": {"news.status"},
    "kavrigo.runtime.evaluations": {"runtime.status", "runtime.replayed"},
    "kavrigo.runtime.decisions": {"decision.action"},
    "kavrigo.risk.evaluations": {"risk.decision", "risk.replayed"},
    "kavrigo.risk.reasons": {"risk.reason"},
    "kavrigo.risk.handoffs": {"risk.outcome"},
    "kavrigo.paper.commands": {"paper.command"},
    "kavrigo.paper.fills": set(),
    "kavrigo.paper.reconciliations": set(),
    "kavrigo.account.commands": {"kind", "replayed"},
    "kavrigo.workflow.stages": {"stage", "status"},
}


def metric_views() -> list[View]:
    return [View(instrument_name="*", aggregation=DropAggregation())] + [
        View(instrument_name=name, attribute_keys=keys) for name, keys in METRICS.items()
    ]


def config_from_env(service: str) -> TelemetryConfig:
    def secret(key: str) -> SecretStr | None:
        value = os.getenv(key)
        return SecretStr(value) if value else None

    return TelemetryConfig.model_validate(
        {
            "service": service,
            "environment": os.getenv("KAVRIGO_ENV", "local"),
            "mode": os.getenv("KAVRIGO_TELEMETRY", "off"),
            "collector": os.getenv("KAVRIGO_OTLP_ENDPOINT") or None,
            "langfuse_endpoint": os.getenv("KAVRIGO_LANGFUSE_ENDPOINT") or None,
            "langfuse_public_key": secret("LANGFUSE_PUBLIC_KEY"),
            "langfuse_secret_key": secret("LANGFUSE_SECRET_KEY"),
        }
    )


@contextmanager
def telemetry_from_env(service: str) -> Iterator[None]:
    config = config_from_env(service)
    if config.mode == "off":
        yield
        return
    resource = Resource(
        {"service.name": config.service, "deployment.environment.name": config.environment}
    )
    # A nonempty explicit header map avoids importing ambient OTLP auth configuration.
    exporter: SpanExporter = ConsoleSpanExporter()
    metric_exporter = ConsoleMetricExporter()
    if config.mode == "otlp":
        assert config.collector is not None
        base = config.collector.rstrip("/")
        exporter = OTLPSpanExporter(
            endpoint=base + "/v1/traces", headers={"x-kavrigo-telemetry": "v1"}, timeout=2
        )
    traces = TracerProvider(
        resource=resource,
        span_limits=SpanLimits(
            max_events=0, max_links=0, max_attributes=32, max_attribute_length=256
        ),
        shutdown_on_exit=False,
    )
    traces.add_span_processor(
        BatchSpanProcessor(
            SafeSpanExporter(exporter, resource),
            max_queue_size=1024,
            max_export_batch_size=128,
            schedule_delay_millis=1000,
        )
    )
    if config.langfuse_endpoint:
        assert config.langfuse_public_key is not None
        assert config.langfuse_secret_key is not None
        token = base64.b64encode(
            (
                config.langfuse_public_key.get_secret_value()
                + ":"
                + config.langfuse_secret_key.get_secret_value()
            ).encode()
        ).decode()
        langfuse = OTLPSpanExporter(
            endpoint=config.langfuse_endpoint,
            headers={"Authorization": "Basic " + token, "x-langfuse-ingestion-version": "4"},
            timeout=2,
        )
        traces.add_span_processor(
            BatchSpanProcessor(
                SafeSpanExporter(langfuse, resource, model_only=True),
                max_queue_size=512,
                max_export_batch_size=64,
                schedule_delay_millis=1000,
            )
        )
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=config.collector.rstrip("/") + "/v1/metrics",
            headers={"x-kavrigo-telemetry": "v1"},
            timeout=2,
        )
        if config.mode == "otlp" and config.collector
        else metric_exporter,
        export_interval_millis=30000,
        export_timeout_millis=3000,
    )
    meters = MeterProvider(
        resource=resource,
        metric_readers=[reader],
        views=metric_views(),
        shutdown_on_exit=False,
        # Exemplars can retain dimensions removed by a View; do not export that side channel.
        exemplar_filter=AlwaysOffExemplarFilter(),
    )
    trace.set_tracer_provider(traces)
    metrics.set_meter_provider(meters)
    try:
        yield
    finally:
        traces.shutdown()
        meters.shutdown(timeout_millis=5000)
