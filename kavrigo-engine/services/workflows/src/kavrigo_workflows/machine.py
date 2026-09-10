"""Replayable account state machine. Only the PostgreSQL repository authorizes new commands."""

from datetime import datetime

from opentelemetry import metrics, trace

from kavrigo_domain import RiskEvaluation, content_hash
from kavrigo_paper.account import detached
from kavrigo_paper.contracts import PaperCommand
from kavrigo_paper.ledger import Ledger
from kavrigo_risk import LocalRiskSession, RiskRecord
from kavrigo_risk.telemetry import RiskTelemetry
from kavrigo_workflows.contracts import (
    AccountCommand,
    AccountDefinition,
    AccountEvent,
    AccountReceipt,
)


class DurableError(ValueError):
    """Closed domain error suitable for non-retryable workflow failure metadata."""


class SilentRiskTelemetry(RiskTelemetry):
    """Historical reconstruction must not emit model/risk telemetry again."""

    def __init__(self) -> None:
        super().__init__(
            tracer=trace.NoOpTracerProvider().get_tracer("reconstruction"),
            meter=metrics.NoOpMeterProvider().get_meter("reconstruction"),
        )

    def evaluated(self, result: RiskEvaluation, *, replayed: bool) -> None:
        pass

    def handed_off(self, outcome: str) -> None:
        pass


class AccountMachine:
    def __init__(self, definition: AccountDefinition) -> None:
        self.definition = detached(definition)
        self.workspace_id = definition.initial_portfolio.workspace_id
        self.now = definition.initial_portfolio.as_of
        self.controls = definition.controls
        self.ledger = Ledger(definition.account_id, definition.initial_portfolio, definition.config)
        self.generation = 1
        self.sequence = 0
        self.chain = content_hash(definition)
        self.risk = self._risk()
        self.intent_ids: set[str] = set()
        self.decision_ids: set[str] = set()

    def _risk(self) -> LocalRiskSession:
        return LocalRiskSession(
            environment="local",
            portfolio=self.ledger.initial,
            controls=self.controls,
            registrations=self.definition.registrations,
            clock=lambda: self.now,
            telemetry=SilentRiskTelemetry(),
        )

    def initial_receipt(self) -> AccountReceipt:
        return AccountReceipt(
            sequence=self.sequence,
            generation=self.generation,
            state_hash=self.chain,
            state=self.ledger.snapshot(),
            committed_at=self.now,
        )

    def apply(self, command: AccountCommand, at: datetime) -> AccountReceipt:
        command = detached(command)
        if command.generation != self.generation:
            raise DurableError("generation_conflict")
        if at < self.now:
            raise DurableError("account_clock_reversed")
        if (
            command.kind in ("orders", "market", "advance")
            and at.date() != self.definition.initial_portfolio.as_of.date()
        ):
            # Daily P&L is not an all-time balance. Until a reviewed rollover command exists,
            # yesterday's gains must never offset today's loss limit or authorize new fills.
            raise DurableError("account_day_rollover_required")
        self.now = at
        records: list[RiskRecord] = []
        if command.kind == "orders":
            for request in command.requests:
                intent = request.intent
                if (
                    intent.order_intent_id in self.intent_ids
                    or intent.decision_id in self.decision_ids
                ):
                    raise DurableError("decision_already_processed")
                if self.ledger.sealed:
                    raise DurableError("batch_sealed")
                if not self.ledger.snapshot().portfolio.is_reconciled:
                    raise DurableError("reconciliation_required")
                result = self.risk.evaluate(request)
                records.append(result)
                permit = self.risk.handoff(
                    workspace_id=self.workspace_id,
                    order_intent_id=intent.order_intent_id,
                    fencing_token=self.controls.fencing_token,
                )
                if permit is not None:
                    self.ledger = self.ledger.apply(
                        PaperCommand(kind="submit", at=at, permit=permit)
                    )
                self.intent_ids.add(intent.order_intent_id)
                self.decision_ids.add(intent.decision_id)
        elif command.kind == "market":
            assert command.book is not None
            commands = tuple(
                (item.order.order_intent_id, item.permit.approval.fencing_token)
                for item in self.ledger.orders.values()
                if item.order.status.is_open
                and item.order.instrument_id == command.book.instrument_id
            )
            with self.risk.execution_guard(
                workspace_id=self.workspace_id, commands=commands
            ) as blocked:
                self.ledger = self.ledger.apply(
                    PaperCommand(kind="market", at=at, book=command.book, blocked_intents=blocked)
                )
        elif command.kind == "cancel":
            self.ledger = self.ledger.apply(
                PaperCommand(kind="cancel", at=at, client_order_id=command.client_order_id)
            )
        elif command.kind == "controls":
            assert command.controls is not None
            self.risk.update_controls(command.controls)
            self.controls = command.controls
        elif command.kind == "advance":
            # Every accepted risk issuance is submitted in the SAME database command. There
            # can be no orphan permit. Old commands/decisions remain deduped across generations.
            self.ledger = self.ledger.begin_generation(at)
            self.generation += 1
            self.risk = self._risk()
        else:
            # An authoritative reconciliation also ages marks; it cannot refresh market data.
            self.ledger.as_of = at
        self.sequence += 1
        state = self.ledger.snapshot()
        self.chain = content_hash(
            {
                "previous": self.chain,
                "sequence": self.sequence,
                "generation": self.generation,
                "command": command,
                "at": at,
                "state": state,
                "risk": self.risk.audit_events,
            }
        )
        return AccountReceipt(
            sequence=self.sequence,
            generation=self.generation,
            state_hash=self.chain,
            state=state,
            risk_records=tuple(records),
            committed_at=at,
        )

    @classmethod
    def reconstruct(
        cls, definition: AccountDefinition, events: tuple[AccountEvent, ...]
    ) -> "AccountMachine":
        machine = cls(definition)
        for event in events:
            if event.sequence != machine.sequence + 1:
                raise DurableError("account_journal_gap")
            result = machine.apply(event.command, event.occurred_at)
            if result.state_hash != event.state_hash:
                raise DurableError("account_journal_mismatch")
        return machine
