from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from kavrigo_domain import AgentDecision, DecisionProposal, ModelProfile, TradingMode
from kavrigo_model_gateway import (
    EmbeddingInput,
    EmbeddingOutput,
    EmbeddingRequest,
    FailureCode,
    GatewayError,
    LocalBudgetLedger,
    LocalModelGateway,
    ModelRequest,
    PromptDefinition,
    ProviderReply,
    RecordedResponse,
    Usage,
)
from kavrigo_model_gateway.validation import digest


async def test_unknown_is_success_and_auditable(build_gateway, request_model):
    gateway, provider = build_gateway()
    result = await gateway.structured(request_model, DecisionProposal)
    assert result.output.is_abstention
    assert result.record.outcome == "success"
    assert result.record.workspace_id == request_model.scope.workspace_id
    assert result.record.agent_version_id == request_model.scope.agent_version_id
    assert result.record.resolved_model_identifier == "mock-v1"
    assert result.record.cost.amount > 0
    assert result.record.tool_calls == 0
    assert result.record.output_hash == digest(result.output.model_dump_json())
    assert provider.call_count == 1


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        "null",
        "[]",
        '{"a":1,"a":2}',
        '{"a":NaN}',
        '{"a":Infinity}',
        '{"state":',
        "```json\n{}\n```",
        '{"risk_override":true}',
    ],
)
async def test_malformed_output_never_enters_domain(build_gateway, request_model, payload):
    gateway, provider = build_gateway(outputs=[payload])
    with pytest.raises(GatewayError) as err:
        await gateway.structured(request_model, DecisionProposal)
    assert err.value.code is FailureCode.SCHEMA_INVALID
    assert err.value.record.schema_validation_failed
    assert err.value.record.cost.amount > 0
    assert err.value.__cause__ is None
    assert provider.call_count == 1


@pytest.mark.parametrize(
    "addition",
    [
        {"workspace_id": "ws_" + "9" * 32},
        {"model_calls": []},
        {"tool_calls": ["submit_order"]},
        {"risk_policy": {"override": True}},
    ],
)
async def test_model_cannot_assign_context_or_tools(
    build_gateway, request_model, output_json, addition
):
    payload = json.loads(output_json) | addition
    gateway, _ = build_gateway(outputs=[json.dumps(payload)])
    with pytest.raises(GatewayError, match="schema_invalid"):
        await gateway.structured(request_model, DecisionProposal)


@pytest.mark.parametrize("amount", [0.1, True, "NaN", "Infinity"])
async def test_money_cannot_be_float_or_nonfinite(
    build_gateway, request_model, output_json, amount
):
    payload = json.loads(output_json) | {
        "state": "bullish",
        "proposed_action": "buy",
        "proposed_notional": {"amount": amount, "currency": "USD"},
    }
    gateway, _ = build_gateway(outputs=[json.dumps(payload)])
    with pytest.raises(GatewayError, match="schema_invalid"):
        await gateway.structured(request_model, DecisionProposal)


async def test_decimal_money_is_exact(build_gateway, request_model, output_json):
    payload = json.loads(output_json) | {
        "state": "bullish",
        "proposed_action": "buy",
        "proposed_notional": {"amount": "0.1", "currency": "USD"},
    }
    gateway, _ = build_gateway(outputs=[json.dumps(payload)])
    result = await gateway.structured(request_model, DecisionProposal)
    assert result.output.proposed_notional.amount == Decimal("0.1")


@pytest.mark.parametrize(
    "payload",
    [
        '{"facts":[],"api_key":"secret"}',
        '{"facts":["api_key=private-value"]}',
        '{"facts":["Bearer private-value"]}',
        '{"facts":["-----BEGIN RSA PRIVATE KEY-----"]}',
        '{"facts":[],"facts":["changed"]}',
    ],
)
async def test_sensitive_or_ambiguous_input_rejected_before_provider(
    build_gateway, request_model, payload
):
    gateway, provider = build_gateway()
    with pytest.raises(GatewayError, match="invalid_input"):
        await gateway.structured(
            request_model.model_copy(update={"input_json": payload}), DecisionProposal
        )
    assert provider.call_count == 0


@pytest.mark.parametrize(
    ("field", "value"), [("profile", ModelProfile.REASON_DEEP), ("prompt_key", "unregistered")]
)
async def test_unsupported_routes_never_call_provider(build_gateway, request_model, field, value):
    gateway, provider = build_gateway()
    with pytest.raises(GatewayError):
        await gateway.structured(request_model.model_copy(update={field: value}), DecisionProposal)
    assert provider.call_count == 0


async def test_cross_tenant_request_rejected(build_gateway, request_model):
    gateway, provider = build_gateway()
    scope = request_model.scope.model_copy(update={"workspace_id": "ws_" + "9" * 32})
    with pytest.raises(GatewayError, match="invalid_input"):
        await gateway.structured(
            request_model.model_copy(update={"scope": scope}), DecisionProposal
        )
    assert provider.call_count == 0


def test_authoritative_output_schema_not_registerable(build_gateway, prompt):
    with pytest.raises(ValueError, match="authoritative"):
        build_gateway(prompts=[replace(prompt, output_type=AgentDecision)])


def test_backtest_requires_explicit_pin(request_model):
    payload = request_model.model_dump()
    payload["scope"]["mode"] = TradingMode.BACKTEST
    with pytest.raises(ValidationError, match="pinned"):
        ModelRequest.model_validate(payload)


async def test_model_fallback_cannot_be_silent(build_gateway, request_model, output_json):
    gateway, provider = build_gateway(
        outputs=[
            ProviderReply(
                model_identifier="different-v2",
                status="completed",
                output_json=output_json,
                usage=Usage(input_tokens=1, output_tokens=1),
            )
        ]
    )
    with pytest.raises(GatewayError, match="model_mismatch") as err:
        await gateway.structured(request_model, DecisionProposal)
    assert err.value.record.resolved_model_identifier == "different-v2"
    assert err.value.record.cost_is_reservation
    assert provider.call_count == 1


@pytest.mark.parametrize(
    ("status", "code"), [("refused", "provider_refused"), ("incomplete", "incomplete")]
)
async def test_refusal_and_incomplete_not_parsed(
    build_gateway, request_model, output_json, status, code
):
    gateway, _ = build_gateway(
        outputs=[
            ProviderReply(
                model_identifier="mock-v1",
                status=status,
                output_json=output_json,
                usage=Usage(input_tokens=1, output_tokens=1),
            )
        ]
    )
    with pytest.raises(GatewayError, match=code):
        await gateway.structured(request_model, DecisionProposal)


@pytest.mark.parametrize(
    "usage",
    [
        None,
        Usage(input_tokens=10_000_000, output_tokens=1),
        Usage(input_tokens=1, output_tokens=4097),
    ],
)
async def test_unknown_or_excess_usage_fails_closed(
    build_gateway, request_model, output_json, usage
):
    gateway, _ = build_gateway(
        outputs=[
            ProviderReply(
                model_identifier="mock-v1", status="completed", output_json=output_json, usage=usage
            )
        ]
    )
    with pytest.raises(GatewayError, match="usage_invalid") as err:
        await gateway.structured(request_model, DecisionProposal)
    assert err.value.record.usage_known is (usage is not None)


async def test_provider_exception_is_sanitized_and_not_retried(build_gateway, request_model):
    gateway, provider = build_gateway(
        outputs=[RuntimeError("provider echoed api_key=secret-value")]
    )
    with pytest.raises(GatewayError, match="provider_unavailable") as err:
        await gateway.structured(request_model, DecisionProposal)
    assert "secret-value" not in str(err.value)
    assert err.value.__cause__ is None
    assert err.value.record.cost_is_reservation
    assert provider.call_count == 1


async def test_timeout_keeps_reservation(build_gateway, request_model, route, blocked_provider):
    provider = blocked_provider
    gateway, _ = build_gateway(
        provider=provider, routes=[route.model_copy(update={"timeout_ms": 5})]
    )
    with pytest.raises(GatewayError, match="timeout") as err:
        await gateway.structured(request_model, DecisionProposal)
    assert provider.cancelled
    assert err.value.record.cost_is_reservation
    with pytest.raises(GatewayError, match="timeout"):
        await gateway.structured(request_model, DecisionProposal)
    assert provider.call_count == 1


async def test_cancellation_propagates_and_duplicate_cannot_resubmit(
    build_gateway, request_model, blocked_provider
):
    provider = blocked_provider
    gateway, _ = build_gateway(provider=provider)
    task = asyncio.create_task(gateway.structured(request_model, DecisionProposal))
    await provider.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(GatewayError, match="cancelled") as err:
        await gateway.structured(request_model, DecisionProposal)
    assert err.value.record.cost_is_reservation
    assert provider.call_count == 1


async def test_concurrent_duplicate_is_in_progress(build_gateway, request_model, blocked_provider):
    provider = blocked_provider
    gateway, _ = build_gateway(provider=provider)
    first = asyncio.create_task(gateway.structured(request_model, DecisionProposal))
    await provider.started.wait()
    try:
        with pytest.raises(GatewayError, match="in_progress"):
            await gateway.structured(request_model, DecisionProposal)
        assert provider.call_count == 1
    finally:
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first


async def test_duplicate_returns_independent_validated_value(build_gateway, request_model):
    gateway, provider = build_gateway()
    first = await gateway.structured(request_model, DecisionProposal)
    first.output.reason_codes.append("modified_by_caller")
    second = await gateway.structured(request_model, DecisionProposal)
    assert "modified_by_caller" not in second.output.reason_codes
    assert second.replayed
    assert second.record == first.record
    assert provider.call_count == 1


async def test_key_reuse_with_changed_input_fails(build_gateway, request_model):
    gateway, provider = build_gateway()
    await gateway.structured(request_model, DecisionProposal)
    changed = request_model.model_copy(update={"input_json": '{"facts":["new fact"]}'})
    with pytest.raises(GatewayError, match="idempotency_conflict"):
        await gateway.structured(changed, DecisionProposal)
    assert provider.call_count == 1


async def test_recorded_replay_and_tampering(build_gateway, request_model):
    gateway, _ = build_gateway()
    response = await gateway.structured(request_model, DecisionProposal)
    artifact = RecordedResponse(
        request_hash=response.record.request_hash,
        output_json=response.output.model_dump_json(),
        record=response.record,
    )
    fresh, provider = build_gateway(outputs=[])
    replay = fresh.replay(request_model, artifact, DecisionProposal)
    assert replay.replayed
    assert replay.output == response.output
    assert provider.call_count == 0
    with pytest.raises(GatewayError, match="replay_mismatch"):
        fresh.replay(
            request_model, artifact.model_copy(update={"output_json": "{}"}), DecisionProposal
        )
    with pytest.raises(GatewayError, match="replay_mismatch"):
        fresh.replay(
            request_model.model_copy(update={"input_json": '{"facts":["different"]}'}),
            artifact,
            DecisionProposal,
        )


async def test_replay_does_not_consume_call_budget(build_gateway, request_model, access):
    access = access.model_copy(
        update={"decision_budget": access.decision_budget.model_copy(update={"max_calls": 1})}
    )
    gateway, provider = build_gateway(agents=[access])
    for _ in range(4):
        await gateway.structured(request_model, DecisionProposal)
    assert provider.call_count == 1


def test_local_implementation_refuses_nonlocal_startup():
    with pytest.raises(ValueError, match="local"):
        LocalBudgetLedger(environment="paper-prod")
    with pytest.raises(ValueError, match="local"):
        LocalModelGateway(
            environment="paper-prod",
            routes=[],
            providers=[],
            prompts=[],
            agents=[],
            workspaces={},
            ledger=LocalBudgetLedger(environment="local"),
        )


def test_cost_independent_of_decimal_context(route):
    expected = route.cost_units(123456, 789)
    with localcontext() as ctx:
        ctx.prec = 3
        assert route.cost_units(123456, 789) == expected


@pytest.mark.parametrize(
    ("vectors", "valid"),
    [
        ([[0.1, 0.2]], True),
        ([[0.1]], False),
        ([[0.1, 0.2], [0.3, 0.4]], False),
        ([[float("inf"), 0]], False),
    ],
)
async def test_embeddings_share_gateway_validation(
    build_gateway, request_model, route, access, vectors, valid
):
    embed_route = route.model_copy(
        update={"profile": ModelProfile.EMBED, "embedding_dimensions": 2}
    )
    embed_access = access.model_copy(
        update={"profiles": (ModelProfile.EMBED,), "prompt_keys": ("embed-v1",)}
    )
    prompt = PromptDefinition(
        "embed-v1", ModelProfile.EMBED, "Embed the supplied text.", EmbeddingInput, EmbeddingOutput
    )
    gateway, provider = build_gateway(
        outputs=[json.dumps({"vectors": vectors})],
        routes=[embed_route],
        agents=[embed_access],
        prompts=[prompt],
    )
    request = EmbeddingRequest(
        scope=request_model.scope,
        idempotency_key="embed-1",
        prompt_key="embed-v1",
        input_json='{"texts":["evidence"]}',
    )
    if valid:
        result = await gateway.embed(request)
        assert result.output.vectors == ((0.1, 0.2),)
    else:
        with pytest.raises(GatewayError, match="schema_invalid"):
            await gateway.embed(request)
    assert provider.call_count == 1
