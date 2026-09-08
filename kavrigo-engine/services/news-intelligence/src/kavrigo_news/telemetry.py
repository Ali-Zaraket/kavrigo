"""Metadata only; do not export raw articles, supporting quotes, URLs or exception values."""

import structlog
from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Tracer

from kavrigo_news.contracts import NewsResult


class NewsTelemetry:
    def __init__(self, *, tracer: Tracer | None = None, meter: Meter | None = None) -> None:
        self.tracer = tracer or trace.get_tracer("kavrigo.news")
        meter = meter or metrics.get_meter("kavrigo.news")
        self.outcomes = meter.create_counter("kavrigo.news.results", unit="{article}")
        self.delay = meter.create_histogram("kavrigo.news.source_age", unit="s")
        self.log = structlog.get_logger(__name__)

    def record(self, result: NewsResult, source_age: float | None) -> None:
        attrs = {"news.status": result.status.value}
        self.outcomes.add(1, attrs)
        if source_age is not None:
            self.delay.record(source_age, attrs)
        trace.get_current_span().set_attribute("news.status", result.status.value)
        self.log.info("news_processed", status=result.status.value, reasons=result.reason_codes)
