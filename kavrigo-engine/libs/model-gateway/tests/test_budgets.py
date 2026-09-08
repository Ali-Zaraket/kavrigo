from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kavrigo_domain import DecisionProposal
from kavrigo_model_gateway import GatewayError, MockProvider, ProviderReply, Route, Usage


def changed(request, index, *, new_cycle=False):
    update = {"idempotency_key": f"call-{index}"}
    if new_cycle:
        update["scope"] = request.scope.model_copy(update={"decision_id": f"dec_{index:032x}"})
    return request.model_copy(update=update)


@pytest.mark.parametrize("which", ["workspace", "agent", "decision"])
async def test_each_cost_cap_rejects_before_dispatch(
    build_gateway, request_model, quota, access, which
):
    workspaces = {access.workspace_id: quota}
    if which == "workspace":
        workspaces[access.workspace_id] = quota.model_copy(update={"daily_usd": Decimal(0)})
    elif which == "agent":
        access = access.model_copy(
            update={"daily_budget": quota.model_copy(update={"daily_usd": Decimal(0)})}
        )
    else:
        access = access.model_copy(
            update={
                "decision_budget": access.decision_budget.model_copy(update={"max_usd": Decimal(0)})
            }
        )
    gateway, provider = build_gateway(agents=[access], workspaces=workspaces)
    with pytest.raises(GatewayError, match="cost_budget"):
        await gateway.structured(request_model, DecisionProposal)
    assert provider.call_count == 0


@pytest.mark.parametrize("which", ["workspace", "agent"])
async def test_rolling_rate_limit_and_expiry(
    build_gateway, request_model, quota, access, output_json, clock, which
):
    limited = quota.model_copy(update={"calls_per_minute": 1})
    workspaces = {access.workspace_id: limited if which == "workspace" else quota}
    if which == "agent":
        access = access.model_copy(update={"daily_budget": limited})
    gateway, provider = build_gateway(
        outputs=[output_json, output_json], agents=[access], workspaces=workspaces
    )
    await gateway.structured(request_model, DecisionProposal)
    clock.seconds = 59.999
    with pytest.raises(GatewayError, match="rate_budget"):
        await gateway.structured(changed(request_model, 2, new_cycle=True), DecisionProposal)
    clock.seconds = 60
    await gateway.structured(changed(request_model, 2, new_cycle=True), DecisionProposal)
    assert provider.call_count == 2


@pytest.mark.parametrize("which", ["workspace", "agent", "decision"])
async def test_each_call_cap(build_gateway, request_model, quota, access, output_json, which):
    workspaces = {access.workspace_id: quota}
    limited = quota.model_copy(update={"calls_per_day": 1})
    if which == "workspace":
        workspaces[access.workspace_id] = limited
    elif which == "agent":
        access = access.model_copy(update={"daily_budget": limited})
    else:
        access = access.model_copy(
            update={"decision_budget": access.decision_budget.model_copy(update={"max_calls": 1})}
        )
    gateway, provider = build_gateway(
        outputs=[output_json, output_json], agents=[access], workspaces=workspaces
    )
    await gateway.structured(request_model, DecisionProposal)
    with pytest.raises(GatewayError, match="call_budget"):
        await gateway.structured(changed(request_model, 2), DecisionProposal)
    assert provider.call_count == 1


async def test_cycle_deadline_shared_across_calls(build_gateway, request_model, clock):
    gateway, provider = build_gateway()
    await gateway.structured(request_model, DecisionProposal)
    clock.seconds = 10
    with pytest.raises(GatewayError, match="timeout"):
        await gateway.structured(changed(request_model, 2), DecisionProposal)
    assert provider.call_count == 1


async def test_decision_budget_survives_midnight(build_gateway, request_model, access, clock):
    access = access.model_copy(
        update={
            "decision_budget": access.decision_budget.model_copy(
                update={"max_calls": 1, "timeout_ms": 120_000}
            )
        }
    )
    gateway, provider = build_gateway(agents=[access])
    await gateway.structured(request_model, DecisionProposal)
    clock.seconds = 20
    with pytest.raises(GatewayError, match="call_budget"):
        await gateway.structured(changed(request_model, 2), DecisionProposal)
    assert provider.call_count == 1


async def test_reservations_prevent_concurrent_overspend(
    build_gateway, request_model, access, quota, blocked_provider
):
    provider = blocked_provider
    quota = quota.model_copy(update={"calls_per_day": 1})
    gateway, _ = build_gateway(provider=provider, workspaces={access.workspace_id: quota})
    first = asyncio.create_task(gateway.structured(request_model, DecisionProposal))
    await provider.started.wait()
    try:
        with pytest.raises(GatewayError, match="call_budget"):
            await gateway.structured(changed(request_model, 2), DecisionProposal)
        assert provider.call_count == 1
    finally:
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first


async def test_workspace_budget_shared_between_agents(build_gateway, request_model, access, quota):
    other = access.model_copy(
        update={"agent_id": "ag_" + "8" * 32, "agent_version_id": "av_" + "8" * 32}
    )
    gateway, provider = build_gateway(
        agents=[access, other],
        workspaces={access.workspace_id: quota.model_copy(update={"calls_per_day": 1})},
    )
    await gateway.structured(request_model, DecisionProposal)
    request = changed(request_model, 2).model_copy(
        update={
            "scope": request_model.scope.model_copy(
                update={"agent_id": other.agent_id, "agent_version_id": other.agent_version_id}
            )
        }
    )
    with pytest.raises(GatewayError, match="call_budget"):
        await gateway.structured(request, DecisionProposal)
    assert provider.call_count == 1


async def test_workspaces_isolated_even_with_same_idempotency_key(
    build_gateway, request_model, access, quota, output_json
):
    other = access.model_copy(update={"workspace_id": "ws_" + "8" * 32})
    gateway, provider = build_gateway(
        outputs=[output_json, output_json],
        agents=[access, other],
        workspaces={access.workspace_id: quota, other.workspace_id: quota},
    )
    first = await gateway.structured(request_model, DecisionProposal)
    second = await gateway.structured(
        request_model.model_copy(
            update={
                "scope": request_model.scope.model_copy(update={"workspace_id": other.workspace_id})
            }
        ),
        DecisionProposal,
    )
    assert first.record.model_call_id != second.record.model_call_id
    assert provider.call_count == 2


async def test_capacity_fails_closed_instead_of_forgetting_spend(build_gateway, request_model):
    gateway, provider = build_gateway(capacity=1)
    await gateway.structured(request_model, DecisionProposal)
    with pytest.raises(GatewayError, match="capacity"):
        await gateway.structured(changed(request_model, 2), DecisionProposal)
    duplicate = await gateway.structured(request_model, DecisionProposal)
    assert duplicate.replayed
    assert provider.call_count == 1


@pytest.mark.parametrize("known_usage", [False, True])
async def test_unknown_usage_holds_cost_but_known_usage_settles(
    build_gateway, request_model, access, route, output_json, known_usage
):
    class TenTokenMock(MockProvider):
        def input_token_bound(self, request):
            return 10

    # Each admission reserves $0.074: 10 input + 64 output, $0.001/token. Two such
    # reservations exceed the $0.10 decision cap, but two actual $0.002 calls fit.
    route = route.model_copy(
        update={
            "max_output_tokens": 64,
            "input_usd_per_million": Decimal("1000"),
            "output_usd_per_million": Decimal("1000"),
        }
    )
    access = access.model_copy(
        update={
            "decision_budget": access.decision_budget.model_copy(
                update={"max_usd": Decimal("0.10")}
            )
        }
    )
    reply = ProviderReply(
        model_identifier="mock-v1",
        status="completed",
        output_json=output_json,
        usage=Usage(input_tokens=1, output_tokens=1),
    )
    provider = TenTokenMock([reply if known_usage else RuntimeError("unavailable"), reply])
    gateway, _ = build_gateway(provider=provider, routes=[route], agents=[access])
    if known_usage:
        first = await gateway.structured(request_model, DecisionProposal)
        assert first.record.cost.amount == Decimal("0.002")
        await gateway.structured(changed(request_model, 2), DecisionProposal)
        assert provider.call_count == 2
    else:
        with pytest.raises(GatewayError, match="provider_unavailable") as err:
            await gateway.structured(request_model, DecisionProposal)
        assert err.value.record.cost.amount == Decimal("0.074")
        assert err.value.record.cost_is_reservation
        with pytest.raises(GatewayError, match="cost_budget"):
            await gateway.structured(changed(request_model, 2), DecisionProposal)
        assert provider.call_count == 1


@given(
    input_tokens=st.integers(0, 1_000_000),
    output_tokens=st.integers(0, 32768),
    input_price=st.integers(0, 10**24 - 1),
    output_price=st.integers(0, 10**24 - 1),
)
def test_cost_reservation_is_a_ceiling(input_tokens, output_tokens, input_price, output_price):
    # Build fixed-point prices from strings, avoiding the ambient Decimal context even here.
    def price(n):
        return Decimal(f"{n // 10**12}.{n % 10**12:012d}")

    route = Route(
        profile="reason_balanced",
        provider="mock",
        model_identifier="mock-v1",
        pricing_version="fixture-v1",
        input_usd_per_million=price(input_price),
        output_usd_per_million=price(output_price),
        max_input_tokens=1_000_000,
        max_output_tokens=32768,
        timeout_ms=1000,
    )
    units = route.cost_units(input_tokens, output_tokens)
    exact_numerator = input_price * input_tokens + output_price * output_tokens
    assert units * 1_000_000 >= exact_numerator
    assert units * 1_000_000 - exact_numerator < 1_000_000
