"""Bounded local scanner -> analysis -> portfolio pipeline (§6). No execution capability."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import localcontext
from threading import RLock

from pydantic import ValidationError

from kavrigo_domain import (
    AgentDecision,
    DecisionProposal,
    ModelCallRecord,
    Money,
    TradingMode,
    content_hash,
)
from kavrigo_domain.base import utc_now
from kavrigo_domain.numeric import DECIMAL_CONTEXT
from kavrigo_model_gateway import (
    CallScope,
    GatewayError,
    ModelGateway,
    ModelRequest,
    registered_prompt_hash,
)
from kavrigo_runtime.analyzer import (
    abstain,
    analysis_prompt,
    bind,
    proposal_reason,
    relevant_evidence,
)
from kavrigo_runtime.contracts import (
    AnalysisInput,
    EvaluationRequest,
    EvaluationResult,
    EvaluationStatus,
    NetworkContext,
    NetworkContextProvider,
    RuntimeRegistration,
)
from kavrigo_runtime.portfolio import allocate
from kavrigo_runtime.scanner import FrozenNetworkContexts, scan
from kavrigo_runtime.telemetry import RuntimeTelemetry
from kavrigo_runtime.validation import eligible_evidence, input_reason, network_hash


class LocalAgentRuntime:
    def __init__(
        self,
        *,
        environment: str,
        gateway: ModelGateway,
        registrations: tuple[RuntimeRegistration, ...],
        network: NetworkContextProvider | None = None,
        clock: Callable[[], datetime] = utc_now,
        capacity: int = 10_000,
        telemetry: RuntimeTelemetry | None = None,
    ) -> None:
        if environment != "local":
            raise ValueError("local agent runtime requires local environment")
        if not 1 <= capacity <= 100_000:
            raise ValueError("invalid runtime capacity")
        self._registrations: dict[str, RuntimeRegistration] = {}
        for value in registrations:
            item = RuntimeRegistration.model_validate_json(value.model_dump_json())
            version = item.agent_version
            if version.spec_hash != content_hash(version.spec):
                raise ValueError("registered agent spec hash mismatch")
            if version.prompt_hash != registered_prompt_hash(
                analysis_prompt(version.spec.model_policy.profile)
            ):
                raise ValueError("registered agent prompt hash mismatch; create a new version")
            if version.spec.mode is TradingMode.BACKTEST and item.pinned_model_identifier is None:
                raise ValueError("backtest runtime requires a pinned model")
            if version.agent_version_id in self._registrations:
                raise ValueError("duplicate agent version registration")
            self._registrations[version.agent_version_id] = item
        self._gateway = gateway
        self._network = network or FrozenNetworkContexts()
        self._clock = clock
        self._capacity = capacity
        self._telemetry = telemetry or RuntimeTelemetry()
        self._lock = RLock()
        self._cache: dict[tuple[str, str], tuple[str, str | None]] = {}
        self._counts: dict[tuple[str, str, str], int] = {}
        self._last: dict[tuple[str, str], datetime] = {}

    async def evaluate(self, value: EvaluationRequest) -> EvaluationResult:
        with (
            localcontext(DECIMAL_CONTEXT),
            self._telemetry.tracer.start_as_current_span(
                "agent.evaluate",
                record_exception=False,
                set_status_on_exception=False,
            ),
        ):
            result, replayed = await self._evaluate(value)
            self._telemetry.record(result, replayed=replayed)
            return result

    async def _evaluate(self, value: EvaluationRequest) -> tuple[EvaluationResult, bool]:
        request = EvaluationRequest.model_validate_json(value.model_dump_json())
        registration = self._registrations.get(request.agent_version_id)
        request_hash = content_hash(request)
        policy_hash = content_hash(registration.policy) if registration else content_hash({})
        run_calls: list[ModelCallRecord] = []

        def result(status: EvaluationStatus, *reasons: str) -> EvaluationResult:
            return EvaluationResult(
                status=status,
                workspace_id=request.workspace_id,
                agent_version_id=request.agent_version_id,
                request_hash=request_hash,
                runtime_policy_hash=policy_hash,
                reason_codes=reasons,
                model_calls=tuple(run_calls),
            )

        if registration is None or registration.agent_version.workspace_id != request.workspace_id:
            return result(EvaluationStatus.REFUSED, "unauthorized_version"), False
        version, policy = registration.agent_version, registration.policy
        key = (request.workspace_id, request.idempotency_key)
        with self._lock:
            prior = self._cache.get(key)
            if prior:
                prior_hash, stored = prior
                if prior_hash != request_hash:
                    return result(EvaluationStatus.REFUSED, "idempotency_conflict"), False
                if stored is None:
                    return result(EvaluationStatus.IN_PROGRESS, "evaluation_in_progress"), False
                return EvaluationResult.model_validate_json(stored), True
        now = self._clock()
        if now.tzinfo is not None:
            now = now.astimezone(UTC)
        reason = input_reason(request, version, policy, now)
        if reason:
            return result(EvaluationStatus.REFUSED, reason), False
        candidates = scan(request.snapshot, version, policy.scanner)
        agent_key = (request.workspace_id, version.agent_id)
        day_key = (*agent_key, now.date().isoformat())
        with self._lock:
            if key in self._cache:
                return result(EvaluationStatus.IN_PROGRESS, "evaluation_in_progress"), False
            if len(self._cache) >= self._capacity:
                return result(EvaluationStatus.REFUSED, "runtime_capacity"), False
            last = self._last.get(agent_key)
            if (
                last is not None
                and (now - last).total_seconds() < version.spec.schedule.decision_interval_seconds
            ):
                return result(EvaluationStatus.REFUSED, "decision_interval"), False
            remaining = version.spec.schedule.max_decisions_per_day - self._counts.get(day_key, 0)
            if remaining <= 0:
                return result(EvaluationStatus.REFUSED, "daily_decision_budget"), False
            selected = candidates[: min(remaining, policy.max_calls_per_cycle)]
            self._counts[day_key] = self._counts.get(day_key, 0) + len(selected)
            self._last[agent_key] = now
            self._cache[key] = (request_hash, None)

        completed = result(EvaluationStatus.REFUSED, "evaluation_interrupted")
        try:
            try:
                contexts = (
                    tuple(
                        NetworkContext.model_validate_json(item.model_dump_json())
                        for item in self._network.frozen_contexts()
                    )
                    if version.spec.analysis.network_context
                    else ()
                )
            except Exception:
                completed = result(EvaluationStatus.REFUSED, "network_unavailable")
                return completed, False
            if len(contexts) > 16 or len({c.context_id for c in contexts}) != len(contexts):
                completed = result(EvaluationStatus.REFUSED, "network_capacity")
                return completed, False
            eligible = eligible_evidence(request, version)
            known = {e.evidence_id for e in eligible}
            if any(
                c.content_hash != network_hash(c)
                or c.known_at > request.snapshot.as_of
                or not set(c.evidence_refs) <= known
                for c in contexts
            ):
                completed = result(EvaluationStatus.REFUSED, "invalid_network_context")
                return completed, False
            decisions: list[AgentDecision] = []
            cycle_reasons: list[str] = []
            if not candidates:
                cycle_reasons.append("no_candidates")
            if len(selected) < len(candidates):
                cycle_reasons.append("cycle_decision_budget")
            features = {f.instrument_id.value: f for f in request.snapshot.features}
            # A single cooperative deadline also bounds the whole cycle, even when individual
            # provider calls have shorter timeouts. Gateway records cancelled/unknown spend.
            try:
                async with asyncio.timeout(version.spec.model_policy.timeout_seconds):
                    for candidate in selected:
                        instrument = candidate.instrument_id
                        evidence = relevant_evidence(eligible, instrument.value, instrument.base)
                        network = tuple(
                            c
                            for c in contexts
                            if any(i.value == instrument.value for i in c.instruments)
                            and c.valid_until > request.snapshot.as_of
                        )
                        held = next(
                            (
                                p.market_value
                                for p in request.portfolio.positions
                                if p.instrument_id.value == instrument.value
                            ),
                            None,
                        )
                        facts = AnalysisInput(
                            instrument=instrument,
                            as_of=request.snapshot.as_of,
                            horizon_minutes=request.horizon_minutes,
                            market_regime=request.snapshot.regime,
                            features=features[instrument.value],
                            evidence=evidence[:64],
                            network=network,
                            available_cash=request.portfolio.available_cash,
                            current_position_value=held or Money.zero(instrument.quote),
                            min_evidence_items=version.spec.evidence.min_evidence_items,
                            require_contradicting_evidence=version.spec.evidence.require_contradicting_evidence,
                        )
                        reason = None
                        if self._clock() >= candidate.expires_at:
                            reason = "candidate_expired"
                        elif not version.spec.analysis.asset_analyzer:
                            reason = "analyzer_disabled"
                        elif len(evidence) > 64:
                            reason = "evidence_capacity"
                        elif len(evidence) < version.spec.evidence.min_evidence_items:
                            reason = "insufficient_evidence"
                        elif version.spec.analysis.network_context and (
                            not network or any(c.health != "normal" for c in network)
                        ):
                            reason = "unknown_network_context"
                        decision_id = "dec_" + content_hash([request_hash, instrument.value])[7:39]
                        calls: tuple[ModelCallRecord, ...] = ()
                        proposal = abstain(request.horizon_minutes, reason or "model_unavailable")
                        if reason is None:
                            try:
                                model_request = ModelRequest(
                                    scope=CallScope(
                                        workspace_id=version.workspace_id,
                                        agent_id=version.agent_id,
                                        agent_version_id=version.agent_version_id,
                                        decision_id=decision_id,
                                        mode=version.spec.mode,
                                    ),
                                    idempotency_key="asset-" + decision_id[4:],
                                    profile=version.spec.model_policy.profile,
                                    prompt_key=analysis_prompt(
                                        version.spec.model_policy.profile
                                    ).key,
                                    input_json=facts.model_dump_json(),
                                    pinned_model_identifier=registration.pinned_model_identifier,
                                )
                                response = await self._gateway.structured(
                                    model_request, DecisionProposal
                                )
                                calls = (response.record,)
                                run_calls.append(response.record)
                                proposed = DecisionProposal.model_validate_json(
                                    response.output.model_dump_json()
                                )
                                reason = proposal_reason(proposed, facts, version)
                                proposal = (
                                    abstain(request.horizon_minutes, reason) if reason else proposed
                                )
                            except GatewayError as error:
                                calls = (error.record,) if error.record is not None else ()
                                run_calls.extend(calls)
                                proposal = abstain(
                                    request.horizon_minutes, "model_" + error.code.value
                                )
                            except asyncio.CancelledError:
                                terminal = self._gateway.record_for(model_request, DecisionProposal)
                                if terminal is not None:
                                    run_calls.append(terminal)
                                raise
                            except ValidationError:
                                proposal = abstain(request.horizon_minutes, "invalid_model_output")
                        decided_at = self._clock()
                        if (
                            decided_at.tzinfo is None
                            or decided_at < now
                            or decided_at >= candidate.expires_at
                            or any(c.valid_until <= decided_at for c in network)
                            or (decided_at - request.snapshot.as_of).total_seconds() * 1000
                            > policy.max_snapshot_age_ms
                        ):
                            proposal = abstain(request.horizon_minutes, "decision_expired")
                            decided_at = now if decided_at.tzinfo is None else max(now, decided_at)
                        decisions.append(
                            bind(
                                proposal,
                                version=version,
                                snapshot_id=request.snapshot.snapshot_id,
                                facts=facts,
                                decision_id=decision_id,
                                decided_at=decided_at,
                                calls=calls,
                            )
                        )
            except TimeoutError:
                # Previously completed proposals are retained for inspection but receive zero
                # allocation when the cycle did not finish. No partial execution capability.
                completed = result(EvaluationStatus.REFUSED, "cycle_timeout").model_copy(
                    update={
                        "decisions": tuple(decisions),
                        "candidates": selected,
                        "network_contexts": contexts,
                    }
                )
                return completed, False
            completed = result(EvaluationStatus.COMPLETED, *cycle_reasons).model_copy(
                update={
                    "candidates": selected,
                    "decisions": tuple(decisions),
                    "network_contexts": contexts,
                    "portfolio_decision": allocate(tuple(decisions), request.portfolio, policy),
                }
            )
            return completed, False
        finally:
            with self._lock:
                terminal_result = completed.model_copy(update={"model_calls": tuple(run_calls)})
                self._cache[key] = (request_hash, terminal_result.model_dump_json())
