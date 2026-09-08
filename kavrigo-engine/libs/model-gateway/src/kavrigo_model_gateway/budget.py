"""Atomic local mock reservations. This is NOT a persistent billing ledger.

Reservations precede provider dispatch. Unknown usage retains the entire reservation, because
a client timeout does not prove the provider stopped billing. All updates are synchronous
under one lock, including finalization during cancellation. Rate limits use a rolling minute;
daily spend/call counts use UTC; the decision cap never resets at midnight or version edits.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from time import monotonic
from typing import Protocol

from kavrigo_domain import ModelCallRecord, utc_now
from kavrigo_model_gateway.contracts import (
    AgentAccess,
    FailureCode,
    GatewayError,
    ModelRequest,
    RecordedResponse,
    ScopeBudget,
    usd_units,
)


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def now(self) -> datetime: ...


class SystemClock:
    def monotonic(self) -> float:
        return monotonic()

    def now(self) -> datetime:
        return utc_now()


@dataclass
class _Counter:
    units: int = 0
    calls: int = 0


@dataclass
class Ticket:
    fingerprint: str
    reserved_units: int
    counters: tuple[_Counter, ...]
    deadline: float
    record: ModelCallRecord | None = None
    artifact: RecordedResponse | None = None


@dataclass
class _Cycle:
    version: str
    deadline: float
    counter: _Counter = field(default_factory=_Counter)


class LocalBudgetLedger:
    """Bounded, shared within ONE local process; never evicts idempotency or spend state.

    Refuses non-local startup. Paid/distributed use needs a durable PostgreSQL reservation and
    idempotency implementation before a network provider can be enabled (ADR 0022).
    """

    def __init__(
        self, *, environment: str, clock: Clock | None = None, capacity: int = 10_000
    ) -> None:
        if environment != "local":
            raise ValueError("local model budgets require environment=local")
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.clock = clock or SystemClock()
        self._capacity = capacity
        self._lock = RLock()
        self._tickets: dict[tuple[str, str], Ticket] = {}
        self._days: dict[tuple[str, ...], _Counter] = {}
        self._rates: dict[tuple[str, ...], deque[float]] = {}
        self._cycles: dict[tuple[str, str, str], _Cycle] = {}

    def reserve(
        self,
        request: ModelRequest,
        fingerprint: str,
        units: int,
        access: AgentAccess,
        workspace_budget: ScopeBudget,
    ) -> tuple[Ticket, bool]:
        with self._lock:
            scope = request.scope
            key = (scope.workspace_id, request.idempotency_key)
            previous = self._tickets.get(key)
            if previous is not None:
                if previous.fingerprint != fingerprint:
                    raise GatewayError(FailureCode.IDEMPOTENCY_CONFLICT)
                if previous.record is None:
                    raise GatewayError(FailureCode.IN_PROGRESS)
                return previous, False
            if len(self._tickets) >= self._capacity:
                raise GatewayError(FailureCode.CAPACITY)
            now = self.clock.monotonic()
            day = self.clock.now().date().isoformat()
            ws = (scope.workspace_id,)
            agent = (scope.workspace_id, scope.agent_id)
            cycle_key = (*agent, scope.decision_id)
            cycle = self._cycles.get(cycle_key)
            if cycle is None:
                cycle = _Cycle(
                    scope.agent_version_id, now + access.decision_budget.timeout_ms / 1000
                )
            if cycle.version != scope.agent_version_id:
                raise GatewayError(FailureCode.IDEMPOTENCY_CONFLICT)
            if now >= cycle.deadline:
                raise GatewayError(FailureCode.TIMEOUT)
            counters: list[_Counter] = []
            for identity, policy in ((ws, workspace_budget), (agent, access.daily_budget)):
                counter = self._days.get((*identity, day), _Counter())
                if counter.units + units > usd_units(policy.daily_usd):
                    raise GatewayError(FailureCode.COST_BUDGET)
                if counter.calls >= policy.calls_per_day:
                    raise GatewayError(FailureCode.CALL_BUDGET)
                timestamps = self._rates.get(identity, deque())
                while timestamps and timestamps[0] <= now - 60:
                    timestamps.popleft()
                if len(timestamps) >= policy.calls_per_minute:
                    raise GatewayError(FailureCode.RATE_BUDGET)
                counters.append(counter)
            if cycle.counter.units + units > usd_units(access.decision_budget.max_usd):
                raise GatewayError(FailureCode.COST_BUDGET)
            if cycle.counter.calls >= access.decision_budget.max_calls:
                raise GatewayError(FailureCode.CALL_BUDGET)
            # No mutation that consumes quota until every scope passes admission.
            self._cycles[cycle_key] = cycle
            for scope_key, counter in zip((ws, agent), counters, strict=True):
                self._days[(*scope_key, day)] = counter
                self._rates.setdefault(scope_key, deque()).append(now)
            counters.append(cycle.counter)
            for counter in counters:
                counter.units += units
                counter.calls += 1
            ticket = Ticket(fingerprint, units, tuple(counters), cycle.deadline)
            self._tickets[key] = ticket
            return ticket, True

    def record_for(self, request: ModelRequest, fingerprint: str) -> ModelCallRecord | None:
        with self._lock:
            ticket = self._tickets.get((request.scope.workspace_id, request.idempotency_key))
            if ticket is None:
                return None
            if ticket.fingerprint != fingerprint:
                raise GatewayError(FailureCode.IDEMPOTENCY_CONFLICT)
            return (
                ModelCallRecord.model_validate_json(ticket.record.model_dump_json())
                if ticket.record
                else None
            )

    def finish(
        self,
        ticket: Ticket,
        *,
        actual_units: int | None,
        record: ModelCallRecord,
        output_json: str | None,
    ) -> None:
        with self._lock:
            if ticket.record is not None:
                raise RuntimeError("model reservation already finalized")
            if actual_units is not None:
                # Even a provider violating its bound is accounted for, never clamped away.
                for counter in ticket.counters:
                    counter.units += actual_units - ticket.reserved_units
            ticket.record = record
            if output_json is not None:
                ticket.artifact = RecordedResponse(
                    request_hash=ticket.fingerprint, output_json=output_json, record=record
                )
