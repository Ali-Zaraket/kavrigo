import ast
import asyncio
import json
from pathlib import Path

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from structlog.testing import capture_logs

from kavrigo_domain import Money, Position, Quantity
from kavrigo_runtime import EvaluationStatus, LocalAgentRuntime, RuntimeRegistration
from kavrigo_runtime.telemetry import RuntimeTelemetry

from .conftest import BTC


async def test_missing_position_mark_is_never_presented_as_flat(build_runtime, request_cycle):
    position = Position(
        instrument_id=BTC,
        quantity=Quantity(value="1", asset="BTC"),
        realized_pnl=Money.zero("USD"),
        unrealized_pnl=Money.zero("USD"),
    )
    portfolio = request_cycle.portfolio.model_copy(update={"positions": [position]})
    runtime, provider = build_runtime()
    result = await runtime.evaluate(request_cycle.model_copy(update={"portfolio": portfolio}))
    assert result.reason_codes == ("unknown_position_valuation",)
    assert provider.call_count == 0


async def test_runtime_capacity_preserves_previous_result(build_runtime, request_cycle, clock):
    runtime, provider = build_runtime(capacity=1)
    first = await runtime.evaluate(request_cycle)
    clock.seconds += 60
    second = await runtime.evaluate(
        request_cycle.model_copy(update={"idempotency_key": "cycle-two"})
    )
    assert second.reason_codes == ("runtime_capacity",)
    assert await runtime.evaluate(request_cycle) == first
    assert provider.call_count == 2


async def test_cycle_deadline_retains_no_partial_allocation(
    version, policy, contexts, clock, request_cycle
):
    from kavrigo_runtime import FrozenNetworkContexts

    class UnavailableGateway:
        async def structured(self, request, output_type):
            await asyncio.Event().wait()

        def record_for(self, request, output_type):
            return None

    runtime = LocalAgentRuntime(
        environment="local",
        gateway=UnavailableGateway(),
        registrations=(RuntimeRegistration(agent_version=version, policy=policy),),
        network=FrozenNetworkContexts(contexts),
        clock=clock.now,
    )
    result = await runtime.evaluate(request_cycle)
    assert result.status is EvaluationStatus.REFUSED
    assert result.reason_codes == ("cycle_timeout",)
    assert result.portfolio_decision is None
    assert (await runtime.evaluate(request_cycle)) == result


async def test_telemetry_contains_only_metadata(build_runtime, request_cycle):
    traces = TracerProvider()
    exporter = InMemorySpanExporter()
    traces.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    meters = MeterProvider(metric_readers=[reader])
    telemetry = RuntimeTelemetry(traces.get_tracer("test"), meters.get_meter("test"))
    try:
        runtime, _ = build_runtime(telemetry=telemetry)
        with capture_logs() as logs:
            await runtime.evaluate(request_cycle)
            await runtime.evaluate(request_cycle)
        spans = exporter.get_finished_spans()
        assert len(spans) == 2
        assert spans[1].attributes["runtime.replayed"] is True
        for sensitive in ("Liquidity improved", "outage remains", request_cycle.workspace_id):
            assert sensitive not in json.dumps([dict(span.attributes) for span in spans])
        assert "Liquidity improved" not in json.dumps(logs)
        assert all(not span.events for span in spans)
        data = reader.get_metrics_data()
        metrics = {
            m.name: m for r in data.resource_metrics for s in r.scope_metrics for m in s.metrics
        }
        assert sum(p.value for p in metrics["kavrigo.runtime.evaluations"].data.data_points) == 2
        assert sum(p.value for p in metrics["kavrigo.runtime.decisions"].data.data_points) == 2
    finally:
        traces.shutdown()
        meters.shutdown()


def test_local_startup_refusal(version, policy):
    with pytest.raises(ValueError, match="local environment"):
        LocalAgentRuntime(
            environment="production",
            gateway=None,
            registrations=(RuntimeRegistration(agent_version=version, policy=policy),),
        )


def test_runtime_has_no_order_or_exchange_capability():
    import kavrigo_runtime

    prohibited_modules = {
        "openai",
        "agents",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "boto3",
        "ccxt",
        "os",
        "kavrigo_nautilus",
    }
    prohibited_types = {"OrderIntent", "ApprovedOrderIntent", "Order", "Fill", "RiskEvaluation"}
    for path in Path(kavrigo_runtime.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {alias.name.split(".")[0] for alias in node.names} & prohibited_modules
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in prohibited_modules
                assert not {alias.name for alias in node.names} & prohibited_types
