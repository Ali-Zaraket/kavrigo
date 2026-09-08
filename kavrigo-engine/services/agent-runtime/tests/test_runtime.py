import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest

from kavrigo_domain import ModelProfile, ProposedAction, content_hash
from kavrigo_model_gateway import MockProvider
from kavrigo_runtime import EvaluationStatus, FrozenNetworkContexts, network_hash, scan

from .conftest import BTC, ETH, seal_snapshot


async def test_scanner_analysis_portfolio_and_replay(build_runtime, request_cycle, version, clock):
    runtime, provider = build_runtime()
    result = await runtime.evaluate(request_cycle)
    assert result.status is EvaluationStatus.COMPLETED
    assert [c.instrument_id for c in result.candidates] == [BTC, ETH]
    assert len(result.decisions) == 2
    assert provider.call_count == 2
    for decision in result.decisions:
        assert decision.proposed_action is ProposedAction.BUY
        assert decision.workspace_id == version.workspace_id
        assert decision.agent_version_id == version.agent_version_id
        assert decision.snapshot_id == request_cycle.snapshot.snapshot_id
        assert decision.decided_at == clock.now()
        assert decision.model_calls[0].decision_id == decision.decision_id
        assert decision.model_calls[0].prompt_hash == version.prompt_hash
    amounts = [a.allocated_notional.amount for a in result.portfolio_decision.allocations]
    assert amounts == [Decimal("300"), Decimal("100")]
    assert result.portfolio_decision.allocations[1].reason_codes == ("allocation_reduced",)
    replay = await runtime.evaluate(request_cycle)
    assert replay == result
    assert provider.call_count == 2
    # Frozen Pydantic models contain nested lists: replay must clone, never share them.
    result.decisions[0].reason_codes.append("tampered")
    assert "tampered" not in (await runtime.evaluate(request_cycle)).decisions[0].reason_codes


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"workspace_id": "ws_" + "9" * 32}, "unauthorized_version"),
        ({"agent_version_id": "av_" + "9" * 32}, "unauthorized_version"),
        ({"horizon_minutes": 15}, "unsupported_horizon"),
    ],
)
async def test_invalid_scope_never_calls_model(build_runtime, request_cycle, change, reason):
    runtime, provider = build_runtime()
    result = await runtime.evaluate(request_cycle.model_copy(update=change))
    assert result.status is EvaluationStatus.REFUSED
    assert result.reason_codes == (reason,)
    assert provider.call_count == 0


@pytest.mark.parametrize(
    "boundary",
    [
        "snapshot",
        "feature",
        "future_evidence",
        "evidence_refs",
        "future_portfolio",
        "stale_portfolio",
        "sequence",
    ],
)
async def test_frozen_input_validation(build_runtime, request_cycle, clock, boundary):
    request = request_cycle
    if boundary == "snapshot":
        snapshot = request.snapshot.model_copy(update={"content_hash": "sha256:" + "0" * 64})
        request = request.model_copy(update={"snapshot": snapshot})
        reason = "snapshot_hash_mismatch"
    elif boundary == "feature":
        features = [
            f.model_copy(update={"values": {"return_5m": Decimal("100")}})
            for f in request.snapshot.features
        ]
        request = request.model_copy(
            update={
                "snapshot": seal_snapshot(
                    request.snapshot.model_copy(update={"features": features})
                )
            }
        )
        reason = "feature_hash_mismatch"
    elif boundary == "future_evidence":
        items = (
            request.evidence[0].model_copy(
                update={"ingested_at": clock.now() + timedelta(seconds=1)}
            ),
            request.evidence[1],
        )
        request = request.model_copy(update={"evidence": items})
        reason = "future_evidence"
    elif boundary == "evidence_refs":
        request = request.model_copy(update={"evidence": request.evidence[:1]})
        reason = "evidence_snapshot_mismatch"
    elif boundary == "future_portfolio":
        request = request.model_copy(
            update={
                "portfolio": request.portfolio.model_copy(
                    update={"as_of": clock.now() + timedelta(seconds=1)}
                )
            }
        )
        reason = "future_portfolio"
    elif boundary == "stale_portfolio":
        request = request.model_copy(
            update={
                "portfolio": request.portfolio.model_copy(
                    update={"as_of": clock.now() - timedelta(hours=1)}
                )
            }
        )
        reason = "stale_portfolio"
    else:
        quality = request.snapshot.quality.model_copy(update={"sequence_complete": False})
        request = request.model_copy(
            update={
                "snapshot": seal_snapshot(request.snapshot.model_copy(update={"quality": quality}))
            }
        )
        reason = "unhealthy_snapshot"
    runtime, provider = build_runtime()
    result = await runtime.evaluate(request)
    assert result.reason_codes == (reason,)
    assert result.portfolio_decision is None
    assert provider.call_count == 0


async def test_unflagged_evidence_is_inspected_for_contradictions(build_runtime, request_cycle):
    items = tuple(
        e.model_copy(update={"is_contradictory_candidate": False}) for e in request_cycle.evidence
    )
    runtime, provider = build_runtime()
    result = await runtime.evaluate(request_cycle.model_copy(update={"evidence": items}))
    assert result.status is EvaluationStatus.COMPLETED
    assert provider.call_count == 2
    assert all(d.proposed_action is ProposedAction.BUY for d in result.decisions)
    assert all(d.contradicting_evidence_refs == [items[1].evidence_id] for d in result.decisions)


@pytest.mark.parametrize("network_state", ["missing", "degraded", "expired", "future", "bad_hash"])
async def test_network_unavailable_never_trades(
    build_runtime, request_cycle, contexts, clock, network_state
):
    context = contexts[0]
    if network_state == "missing":
        configured = ()
    else:
        change = {
            "degraded": {"health": "degraded"},
            "expired": {"valid_until": clock.now()},
            "future": {"known_at": clock.now() + timedelta(seconds=1)},
            "bad_hash": {"content_hash": "sha256:" + "0" * 64},
        }[network_state]
        context = context.model_copy(update=change)
        if network_state != "bad_hash":
            context = context.model_copy(update={"content_hash": network_hash(context)})
        configured = (context,)
    runtime, provider = build_runtime(network=FrozenNetworkContexts(configured))
    result = await runtime.evaluate(request_cycle)
    assert not result.decisions or all(d.is_abstention for d in result.decisions)
    assert provider.call_count == 0


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"evidence_refs": ["ev_" + "9" * 32]}, "unsupported_evidence_reference"),
        ({"contradicting_evidence_refs": []}, "insufficient_supported_evidence"),
        ({"estimated_cost_bps": "-1"}, "unknown_estimated_cost"),
        (
            {"proposed_notional": {"amount": "300", "currency": "USDT"}},
            "proposal_currency_mismatch",
        ),
        ({"workspace_id": "ws_" + "9" * 32}, "model_schema_invalid"),
        ({"risk_evaluation_id": "re_" + "9" * 32}, "model_schema_invalid"),
        ({"tools": ["exchange.submit"]}, "model_schema_invalid"),
    ],
)
async def test_model_cannot_invent_evidence_or_authority(
    build_runtime, request_cycle, proposal, changes, reason
):
    output = json.dumps(proposal.model_dump(mode="json") | changes)
    runtime, provider = build_runtime(outputs=[output, output])
    result = await runtime.evaluate(request_cycle)
    assert result.portfolio_decision.allocations == ()
    assert all(d.is_abstention for d in result.decisions)
    assert all(d.reason_codes == [reason] for d in result.decisions)
    assert all(len(d.model_calls) == 1 for d in result.decisions)
    assert provider.call_count == 2


async def test_disabled_pack_is_not_sent(build_runtime, request_cycle, version):
    spec = version.spec.model_copy(update={"data_packs": [version.spec.data_packs[1]]})
    configured = version.model_copy(update={"spec": spec, "spec_hash": content_hash(spec)})
    runtime, provider = build_runtime(version_override=configured, network=FrozenNetworkContexts())
    result = await runtime.evaluate(request_cycle)
    assert all(d.reason_codes == ["insufficient_evidence"] for d in result.decisions)
    assert provider.call_count == 0


async def test_idempotency_conflict_and_schedule(build_runtime, request_cycle, clock):
    runtime, provider = build_runtime()
    first = await runtime.evaluate(request_cycle)
    changed = request_cycle.model_copy(update={"horizon_minutes": 15})
    assert (await runtime.evaluate(changed)).reason_codes == ("idempotency_conflict",)
    new_key = request_cycle.model_copy(update={"idempotency_key": "cycle-two"})
    assert (await runtime.evaluate(new_key)).reason_codes == ("decision_interval",)
    assert (await runtime.evaluate(request_cycle)) == first
    assert provider.call_count == 2
    clock.seconds += 301
    assert (await runtime.evaluate(new_key)).reason_codes == ("stale_snapshot",)


async def test_daily_budget_counts_decisions_not_only_paid_calls(
    build_runtime, request_cycle, version, clock
):
    schedule = version.spec.schedule.model_copy(update={"max_decisions_per_day": 2})
    spec = version.spec.model_copy(update={"schedule": schedule})
    configured = version.model_copy(update={"spec": spec, "spec_hash": content_hash(spec)})
    runtime, provider = build_runtime(version_override=configured)
    await runtime.evaluate(request_cycle)
    clock.seconds += 60
    next_request = request_cycle.model_copy(update={"idempotency_key": "cycle-two"})
    assert (await runtime.evaluate(next_request)).reason_codes == ("daily_decision_budget",)
    assert provider.call_count == 2


async def test_model_service_unavailable_is_successful_abstention(build_runtime, request_cycle):
    runtime, _ = build_runtime(outputs=[RuntimeError("private provider failure")] * 2)
    result = await runtime.evaluate(request_cycle)
    assert result.status is EvaluationStatus.COMPLETED
    assert all(d.is_abstention for d in result.decisions)
    assert all(d.model_calls[0].cost_is_reservation for d in result.decisions)
    assert result.portfolio_decision.allocations == ()


class BlockingProvider(MockProvider):
    def __init__(self):
        super().__init__([])
        self.started = asyncio.Event()

    async def complete(self, request):
        self.call_count += 1
        self.started.set()
        await asyncio.Event().wait()


async def test_concurrent_duplicate_and_cancel_are_terminal(build_runtime, request_cycle):
    provider = BlockingProvider()
    runtime, _ = build_runtime(provider=provider)
    task = asyncio.create_task(runtime.evaluate(request_cycle))
    await provider.started.wait()
    assert (await runtime.evaluate(request_cycle)).status is EvaluationStatus.IN_PROGRESS
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    retry = await runtime.evaluate(request_cycle)
    assert retry.status is EvaluationStatus.REFUSED
    assert retry.reason_codes == ("evaluation_interrupted",)
    assert provider.call_count == 1
    assert len(retry.model_calls) == 1
    assert retry.model_calls[0].outcome == "cancelled"
    assert retry.model_calls[0].cost_is_reservation


async def test_model_latency_expiring_snapshot_revokes_proposal(
    build_runtime, request_cycle, proposal, clock
):
    class SlowClockProvider(MockProvider):
        async def complete(self, request):
            response = await super().complete(request)
            clock.seconds += 301
            return response

    runtime, _ = build_runtime(provider=SlowClockProvider([proposal.model_dump_json()] * 2))
    result = await runtime.evaluate(request_cycle)
    assert all(d.is_abstention for d in result.decisions)
    assert result.portfolio_decision.allocations == ()


def test_scanner_is_order_invariant_and_universe_bounded(request_cycle, version, policy):
    expected = scan(request_cycle.snapshot, version, policy.scanner)
    reversed_snapshot = request_cycle.snapshot.model_copy(
        update={"features": list(reversed(request_cycle.snapshot.features))}
    )
    assert scan(reversed_snapshot, version, policy.scanner) == expected
    assert expected[0].interest_score > expected[1].interest_score
    spec = version.spec.model_copy(
        update={"universe": version.spec.universe.model_copy(update={"instruments": [BTC]})}
    )
    assert [
        c.instrument_id
        for c in scan(
            request_cycle.snapshot, version.model_copy(update={"spec": spec}), policy.scanner
        )
    ] == [BTC]


def test_prompt_mismatch_refuses_startup(build_runtime, version):
    with pytest.raises(ValueError, match="prompt hash mismatch"):
        build_runtime(
            version_override=version.model_copy(update={"prompt_hash": "sha256:" + "0" * 64})
        )


def test_api_new_versions_pin_runtime_prompt():
    from kavrigo_api.services.prompts import DEFAULT_PROMPT_VERSION, default_prompt_hash
    from kavrigo_model_gateway import registered_prompt_hash
    from kavrigo_runtime import analysis_prompt

    assert DEFAULT_PROMPT_VERSION == "v2"
    assert default_prompt_hash() == registered_prompt_hash(
        analysis_prompt(ModelProfile.REASON_BALANCED)
    )
    assert default_prompt_hash() == registered_prompt_hash(
        analysis_prompt(ModelProfile.REASON_DEEP)
    )
