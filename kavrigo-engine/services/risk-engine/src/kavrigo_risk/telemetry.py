"""Bounded outcome metadata; no evidence text, credentials, amounts or exception bodies."""

import structlog
from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Tracer

from kavrigo_domain import RiskEvaluation


class RiskTelemetry:
    def __init__(self, tracer: Tracer | None = None, meter: Meter | None = None) -> None:
        self.tracer = tracer or trace.get_tracer("kavrigo.risk")
        meter = meter or metrics.get_meter("kavrigo.risk")
        self.evaluations = meter.create_counter("kavrigo.risk.evaluations", unit="{evaluation}")
        self.reasons = meter.create_counter("kavrigo.risk.reasons", unit="{reason}")
        self.handoffs = meter.create_counter("kavrigo.risk.handoffs", unit="{handoff}")
        self.log = structlog.get_logger(__name__)

    def evaluated(self, result: RiskEvaluation, *, replayed: bool) -> None:
        attributes = {"risk.decision": result.decision.value, "risk.replayed": replayed}
        self.evaluations.add(1, attributes)
        if not replayed:
            for reason in result.reason_codes:
                self.reasons.add(1, {"risk.reason": reason.value})
        trace.get_current_span().set_attributes(attributes)
        self.log.info(
            "risk_evaluated",
            decision=result.decision.value,
            replayed=replayed,
            reasons=[reason.value for reason in result.reason_codes],
        )

    def handed_off(self, outcome: str) -> None:
        self.handoffs.add(1, {"risk.outcome": outcome})
        self.log.info("risk_handoff", outcome=outcome)
