"""Metadata-only diagnostics. The financial journal is not a telemetry export."""

from typing import Literal

import structlog
from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Tracer


class PaperTelemetry:
    def __init__(self, tracer: Tracer | None = None, meter: Meter | None = None) -> None:
        self.tracer = tracer or trace.get_tracer("kavrigo.paper")
        meter = meter or metrics.get_meter("kavrigo.paper")
        self.commands = meter.create_counter("kavrigo.paper.commands", unit="{command}")
        self.fills = meter.create_counter("kavrigo.paper.fills", unit="{fill}")
        self.reconciliations = meter.create_counter(
            "kavrigo.paper.reconciliations", unit="{reconciliation}"
        )
        self.log = structlog.get_logger(__name__)

    def committed(self, kind: Literal["submit", "market", "cancel"], fills: int) -> None:
        self.commands.add(1, {"paper.command": kind})
        if fills:
            self.fills.add(fills)
        self.log.info("paper_command_committed", kind=kind, fill_count=fills)

    def reconciled(self, discovered: int) -> None:
        self.reconciliations.add(1)
        self.log.info("paper_reconciled", discovered_fill_count=discovered)
