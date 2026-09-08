"""Outcome metadata, never model rationale or source bodies."""

import structlog
from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Tracer

from kavrigo_runtime.contracts import EvaluationResult


class RuntimeTelemetry:
    def __init__(self, tracer: Tracer | None = None, meter: Meter | None = None) -> None:
        self.tracer = tracer or trace.get_tracer("kavrigo.runtime")
        meter = meter or metrics.get_meter("kavrigo.runtime")
        self.cycles = meter.create_counter("kavrigo.runtime.evaluations", unit="{evaluation}")
        self.decisions = meter.create_counter("kavrigo.runtime.decisions", unit="{decision}")
        self.log = structlog.get_logger(__name__)

    def record(self, result: EvaluationResult, *, replayed: bool = False) -> None:
        self.cycles.add(1, {"runtime.status": result.status.value, "runtime.replayed": replayed})
        if not replayed:
            for decision in result.decisions:
                self.decisions.add(1, {"decision.action": decision.proposed_action.value})
        span = trace.get_current_span()
        span.set_attribute("runtime.status", result.status.value)
        span.set_attribute("runtime.replayed", replayed)
        self.log.info(
            "agent_evaluation_finished",
            status=result.status.value,
            replayed=replayed,
            reasons=result.reason_codes,
            decision_count=len(result.decisions),
        )
