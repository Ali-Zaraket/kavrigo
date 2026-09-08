import asyncio

import pytest

from kavrigo_domain import DecisionProposal
from kavrigo_model_gateway import FailureCode, GatewayError


async def test_record_lookup_does_not_dispatch_or_charge(build_gateway, request_model):
    gateway, provider = build_gateway()
    assert gateway.record_for(request_model, DecisionProposal) is None
    assert provider.call_count == 0
    result = await gateway.structured(request_model, DecisionProposal)
    assert gateway.record_for(request_model, DecisionProposal) == result.record
    assert provider.call_count == 1
    with pytest.raises(GatewayError) as error:
        gateway.record_for(
            request_model.model_copy(update={"input_json": '{"facts":["changed"]}'}),
            DecisionProposal,
        )
    assert error.value.code is FailureCode.IDEMPOTENCY_CONFLICT


async def test_cancelled_record_is_readable_without_redispatch(
    build_gateway, request_model, blocked_provider
):
    gateway, provider = build_gateway(provider=blocked_provider)
    task = asyncio.create_task(gateway.structured(request_model, DecisionProposal))
    await provider.started.wait()
    assert gateway.record_for(request_model, DecisionProposal) is None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    record = gateway.record_for(request_model, DecisionProposal)
    assert record.outcome == "cancelled"
    assert record.cost_is_reservation
    assert provider.call_count == 1
