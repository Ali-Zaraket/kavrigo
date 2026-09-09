"""A bounded, single-process, local paper account gate; never a distributed execution service.

Approvals reserve resources atomically. Reservations survive local handoff failures and expiry;
only a future broker with authoritative reconciliation can safely release them. Restarting or
recreating this object does not preserve state, so non-local startup is refused.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Literal

from pydantic import ValidationError

from kavrigo_domain import (
    ApprovedOrderIntent,
    DomainModel,
    PortfolioSnapshot,
    RiskPolicy,
    RiskReasonCode,
    RiskScope,
    content_hash,
)
from kavrigo_risk.contracts import (
    PaperRiskPermit,
    RiskAuditEvent,
    RiskControls,
    RiskRecord,
    RiskRegistration,
    RiskRequest,
)
from kavrigo_risk.evaluator import Reservation, evaluate
from kavrigo_risk.telemetry import RiskTelemetry


def _copy[T: DomainModel](model: T) -> T:
    # Frozen Pydantic objects can still contain mutable lists/dicts; model_copy skips
    # validation of updates. Revalidate detached serialized values at every trust boundary.
    serialized = model.model_dump_json(warnings="error")
    if len(serialized.encode("utf-8")) > 2_000_000:
        raise ValueError("risk input exceeds local size bound")
    return type(model).model_validate_json(serialized)


class RiskGateError(ValueError):
    """Closed service errors; exception messages contain no request or provider content."""


@dataclass
class _Entry:
    request: RiskRequest
    record: RiskRecord
    reservation: Reservation | None
    fencing_token: int
    terminal_handoff: bool = False
    issued_permit: PaperRiskPermit | None = None


class LocalRiskSession:
    """One account / frozen portfolio generation, shared across its registered agents.

    Callers must supply authorized registrations, market/evidence and supervisor state. This
    library is not an HTTP authentication layer. Do not create competing sessions for the same
    account. Paper broker/workflow integration must replace this local ledger with durable
    serialized account ownership and reconciliation before continuous operation.
    """

    def __init__(
        self,
        *,
        environment: str,
        portfolio: PortfolioSnapshot,
        controls: RiskControls,
        registrations: tuple[RiskRegistration, ...],
        clock: Callable[[], datetime],
        capacity: int = 1000,
        telemetry: RiskTelemetry | None = None,
    ) -> None:
        if environment != "local":
            raise ValueError("in-memory risk reservations are local-only")
        if not 1 <= capacity <= 100_000:
            raise ValueError("risk capacity must be in 1..100000")
        self._portfolio, self._controls = _copy(portfolio), _copy(controls)
        if controls.workspace_id != portfolio.workspace_id:
            raise ValueError("account controls workspace mismatch")
        if not registrations:
            raise ValueError("risk requires an authorized registration")
        self._registrations: dict[str, RiskRegistration] = {}
        self._networks: dict[str, str] = {}
        shared_policies: dict[RiskScope, str] = {}
        asset_networks: dict[str, str] = {}
        all_policies: dict[str, RiskPolicy] = {}
        for supplied in registrations:
            registration = _copy(supplied)
            version = registration.agent_version
            if version.workspace_id != portfolio.workspace_id:
                raise ValueError("registration workspace mismatch")
            if version.agent_version_id in self._registrations:
                raise ValueError("duplicate agent registration")
            for scope in (RiskScope.GLOBAL, RiskScope.WORKSPACE, RiskScope.PORTFOLIO):
                policies = sorted(
                    (p for p in registration.policies if p.scope is scope),
                    key=lambda p: p.risk_policy_id,
                )
                fingerprint = content_hash(policies)
                if scope in shared_policies and shared_policies[scope] != fingerprint:
                    raise ValueError("agents sharing an account must share upper-scope policies")
                shared_policies[scope] = fingerprint
            for instrument in version.spec.universe.instruments:
                network = registration.networks[instrument.value]
                if asset_networks.get(instrument.base, network) != network:
                    raise ValueError("one asset cannot escape network limits through another venue")
                asset_networks[instrument.base] = network
            for instrument_key, network in registration.networks.items():
                if self._networks.get(instrument_key, network) != network:
                    raise ValueError("conflicting network mapping")
                self._networks[instrument_key] = network
            self._registrations[version.agent_version_id] = registration
            for policy in registration.policies:
                previous_policy = all_policies.get(policy.risk_policy_id)
                if previous_policy is not None and previous_policy != policy:
                    raise ValueError("one policy id cannot have conflicting content")
                all_policies[policy.risk_policy_id] = policy
        if len(all_policies) > 16:
            raise ValueError("local account supports at most 16 distinct policies")
        # Portfolio positions are not attributed to agents yet. Conservatively apply the
        # union to the account, so another agent cannot spend around an earlier tighter cap.
        policies = sorted(
            all_policies.values(), key=lambda p: (list(RiskScope).index(p.scope), p.risk_policy_id)
        )
        for key, registration in self._registrations.items():
            self._registrations[key] = RiskRegistration.model_validate(
                {
                    **registration.model_dump(mode="python"),
                    "policies": [policy.model_dump(mode="python") for policy in policies],
                }
            )
        self._clock, self._capacity = clock, capacity
        self._telemetry = telemetry or RiskTelemetry()
        self._entries: dict[str, _Entry] = {}
        self._keys: dict[str, str] = {}
        self._decisions: dict[str, str] = {}
        self._lock = RLock()
        self._last_now: datetime | None = None
        self._audit: list[RiskAuditEvent] = []

    @property
    def audit_events(self) -> tuple[RiskAuditEvent, ...]:
        with self._lock:
            return tuple(_copy(event) for event in self._audit)

    def _audit_event(
        self,
        kind: Literal["evaluated", "controls_updated", "handoff"],
        outcome: str,
        artifact_hash: str,
        now: datetime,
        reasons: tuple[RiskReasonCode, ...] = (),
    ) -> None:
        if len(self._audit) >= self._capacity * 4:
            raise RiskGateError("audit_capacity_exhausted")
        self._audit.append(
            RiskAuditEvent(
                sequence=len(self._audit) + 1,
                workspace_id=self._portfolio.workspace_id,
                account_id=self._controls.account_id,
                occurred_at=now,
                kind=kind,
                outcome=outcome,
                artifact_hash=artifact_hash,
                controls_hash=content_hash(self._controls),
                reason_codes=reasons,
            )
        )

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise RiskGateError("invalid_clock")
        now = now.astimezone(UTC)
        if self._last_now is not None and now < self._last_now:
            raise RiskGateError("clock_moved_backwards")
        self._last_now = now
        return now

    def update_controls(self, controls: RiskControls) -> None:
        """Trusted supervisor entry point, never exposed to model tools."""
        fresh = _copy(controls)
        with self._lock:
            previous = self._controls
            if (
                fresh.workspace_id != previous.workspace_id
                or fresh.account_id != previous.account_id
                or fresh.version <= previous.version
                or fresh.fencing_token < previous.fencing_token
                or fresh.as_of < previous.as_of
                or fresh.as_of > self._now()
            ):
                raise RiskGateError("invalid_control_refresh")
            self._audit_event("controls_updated", "updated", content_hash(fresh), self._now())
            self._controls = fresh

    def _reservations(self, *, excluding: str | None = None) -> tuple[Reservation, ...]:
        return tuple(
            entry.reservation
            for key, entry in sorted(self._entries.items())
            if entry.reservation is not None and key != excluding
        )

    def evaluate(self, request: RiskRequest) -> RiskRecord:
        try:
            detached = _copy(request)
        except (ValueError, ValidationError):
            raise RiskGateError("invalid_risk_request") from None
        intent = detached.intent
        with self._lock:
            if intent.workspace_id != self._portfolio.workspace_id:
                raise RiskGateError("workspace_mismatch")
            registration = self._registrations.get(intent.agent_version_id)
            if registration is None:
                raise RiskGateError("unregistered_agent_version")
            existing_id = self._keys.get(intent.idempotency_key)
            if existing_id is not None or intent.order_intent_id in self._entries:
                existing = self._entries[existing_id or intent.order_intent_id]
                if content_hash(detached) != existing.record.request_hash:
                    raise RiskGateError("idempotency_conflict")
                self._telemetry.evaluated(existing.record.evaluation, replayed=True)
                return _copy(existing.record)
            if intent.decision_id in self._decisions:
                raise RiskGateError("decision_already_evaluated")
            if len(self._entries) >= self._capacity:
                raise RiskGateError("risk_capacity_exhausted")
            with self._telemetry.tracer.start_as_current_span(
                "risk.evaluate", record_exception=False, set_status_on_exception=False
            ):
                result, reservation = evaluate(
                    detached,
                    registration,
                    self._portfolio,
                    self._controls,
                    self._networks,
                    self._reservations(),
                    self._now(),
                )
                self._audit_event(
                    "evaluated",
                    result.evaluation.decision.value,
                    content_hash(result),
                    result.evaluation.evaluated_at,
                    tuple(result.evaluation.reason_codes),
                )
                self._entries[intent.order_intent_id] = _Entry(
                    detached, result, reservation, self._controls.fencing_token
                )
                self._keys[intent.idempotency_key] = intent.order_intent_id
                self._decisions[intent.decision_id] = intent.order_intent_id
                self._telemetry.evaluated(result.evaluation, replayed=False)
                return _copy(result)

    def handoff(
        self, *, workspace_id: str, order_intent_id: str, fencing_token: int
    ) -> PaperRiskPermit | None:
        """Hand off at most once, rechecking controls and all time-dependent policy.

        Mark consumed before returning. If the caller crashes afterwards, the outcome is unknown
        and the reservation stays held. There is no automatic retry/reset/release shortcut.
        """
        with self._lock:
            if workspace_id != self._portfolio.workspace_id:
                raise RiskGateError("workspace_mismatch")
            entry = self._entries.get(order_intent_id)
            if entry is None:
                raise RiskGateError("unknown_intent")
            if not entry.record.evaluation.is_approved:
                self._telemetry.handed_off("rejected")
                return None
            if entry.terminal_handoff:
                self._telemetry.handed_off("duplicate")
                return None
            now = self._now()
            if (
                type(fencing_token) is not int
                or fencing_token != self._controls.fencing_token
                or fencing_token != entry.fencing_token
            ):
                self._telemetry.handed_off("stale_fence")
                return None
            if now >= entry.record.expires_at:
                self._audit_event("handoff", "expired", content_hash(entry.record), now)
                entry.terminal_handoff = True
                self._telemetry.handed_off("expired")
                return None
            request = entry.request
            checked, _ = evaluate(
                request,
                self._registrations[request.intent.agent_version_id],
                self._portfolio,
                self._controls,
                self._networks,
                self._reservations(excluding=order_intent_id),
                now,
            )
            if (
                not checked.evaluation.is_approved
                or checked.evaluation.approved_notional.amount
                < entry.record.evaluation.approved_notional.amount
            ):
                self._audit_event(
                    "handoff",
                    "recheck_rejected",
                    content_hash(checked),
                    now,
                    tuple(checked.evaluation.reason_codes),
                )
                entry.terminal_handoff = True
                self._telemetry.handed_off("recheck_rejected")
                return None
            intent, record = request.intent, entry.record
            approval = ApprovedOrderIntent(
                order_intent_id=intent.order_intent_id,
                risk_evaluation_id=record.evaluation.risk_evaluation_id,
                workspace_id=intent.workspace_id,
                instrument_id=intent.instrument_id,
                mode=intent.mode,
                side=intent.side,
                order_type=intent.order_type,
                approved_notional=record.evaluation.approved_notional,
                time_in_force=intent.time_in_force,
                client_order_id="paper_"
                + content_hash(
                    {
                        "workspace": workspace_id,
                        "account": record.account_id,
                        "intent": order_intent_id,
                    }
                ).removeprefix("sha256:")[:48],
                fencing_token=fencing_token,
                approved_at=now,
                expires_at=record.expires_at,
            )
            permit = PaperRiskPermit(
                account_id=record.account_id,
                approval=approval,
                record=_copy(record),
                execution=_copy(self._registrations[intent.agent_version_id].execution),
            )
            self._audit_event("handoff", "handed_off", content_hash(permit), now)
            entry.terminal_handoff = True
            entry.issued_permit = _copy(permit)
            self._telemetry.handed_off("approved")
            return permit

    def execution_allowed(
        self, *, workspace_id: str, order_intent_id: str, fencing_token: int
    ) -> bool:
        """Recheck a recorded local issuance before the paper simulator can produce a fill.

        This read does not issue another permit or release a reservation. The consumer must
        obtain its original permit directly from this session and enforce its cash/quantity
        bounds. No caller-supplied approval is accepted here.
        """
        with self._lock:
            if workspace_id != self._portfolio.workspace_id:
                raise RiskGateError("workspace_mismatch")
            entry = self._entries.get(order_intent_id)
            if entry is None or entry.issued_permit is None:
                return False
            now = self._now()
            if (
                type(fencing_token) is not int
                or fencing_token != self._controls.fencing_token
                or fencing_token != entry.fencing_token
                or now >= entry.record.expires_at
            ):
                return False
            checked, _ = evaluate(
                entry.request,
                self._registrations[entry.request.intent.agent_version_id],
                self._portfolio,
                self._controls,
                self._networks,
                self._reservations(excluding=order_intent_id),
                now,
            )
            return (
                checked.evaluation.is_approved
                and checked.evaluation.approved_notional.amount
                >= entry.record.evaluation.approved_notional.amount
            )

    @contextmanager
    def execution_guard(
        self, *, workspace_id: str, commands: tuple[tuple[str, int], ...]
    ) -> Iterator[tuple[str, ...]]:
        """Serialize a local paper commit with supervisor changes and new risk reservations.

        The consumer holds its account lock first. No network/venue I/O belongs in this local
        critical section. Remote execution needs durable fencing, not a Python mutex.
        """
        with self._lock:
            if workspace_id != self._portfolio.workspace_id:
                raise RiskGateError("workspace_mismatch")
            yield tuple(
                intent_id
                for intent_id, token in commands
                if not self.execution_allowed(
                    workspace_id=workspace_id, order_intent_id=intent_id, fencing_token=token
                )
            )
