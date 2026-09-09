"""Local authoritative simulator journal and disposable, explicitly reconciled broker views."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import localcontext
from threading import RLock

from kavrigo_domain import DomainModel, Order, OrderStatus, PortfolioSnapshot, content_hash
from kavrigo_paper.contracts import (
    PaperAccountState,
    PaperBook,
    PaperCommand,
    PaperConfig,
    PaperJournalEntry,
    PaperReconciliation,
    PaperReplay,
)
from kavrigo_paper.ledger import VALIDATION_CONTEXT, Ledger, PaperError
from kavrigo_paper.telemetry import PaperTelemetry
from kavrigo_risk import LocalRiskSession

ZERO_HASH = "sha256:" + "0" * 64
MAX_ARTIFACT_BYTES = 10_000_000


def detached[T: DomainModel](model: T) -> T:
    try:
        with localcontext(VALIDATION_CONTEXT):
            encoded = model.model_dump_json(warnings="error")
            if len(encoded.encode("utf-8")) > MAX_ARTIFACT_BYTES:
                raise ValueError("oversized artifact")
            return type(model).model_validate_json(encoded)
    except ValueError:
        raise PaperError("invalid_paper_artifact") from None


def entry_hash(entry: PaperJournalEntry) -> str:
    return content_hash(entry.model_dump(mode="python", exclude={"entry_hash"}))


def header_hash(account_id: str, initial: PortfolioSnapshot, config: PaperConfig) -> str:
    return content_hash(
        {"format_version": "paper-v1", "account": account_id, "initial": initial, "config": config}
    )


def replay(bundle: PaperReplay) -> PaperAccountState:
    """Pure historical reconstruction; an imported bundle never becomes a submission API."""
    bundle = detached(bundle)
    ledger = Ledger(bundle.account_id, bundle.initial_portfolio, bundle.config)
    previous = header_hash(bundle.account_id, bundle.initial_portfolio, bundle.config)
    for sequence, entry in enumerate(bundle.entries, 1):
        if (
            entry.sequence != sequence
            or entry.previous_hash != previous
            or entry.entry_hash != entry_hash(entry)
        ):
            raise PaperError("journal_integrity_error")
        ledger = ledger.apply(entry.command)
        if content_hash(ledger.snapshot()) != entry.state_hash:
            raise PaperError("journal_state_mismatch")
        previous = entry.entry_hash
    return detached(ledger.snapshot())


class LocalPaperVenue:
    """One local account generation; keep this object alive across broker-view reconnects.

    The journal is the authority within this process. No persistence, network or private venue
    exists here. Restarting this object is not recovery: steps 12/13's deployed ledger must
    provide durable idempotency before continuous operation. All model/runtime outputs enter
    through the actual risk session; callers cannot submit a permit or a fill.
    """

    def __init__(
        self,
        *,
        environment: str,
        account_id: str,
        initial_portfolio: PortfolioSnapshot,
        config: PaperConfig,
        risk: LocalRiskSession,
        clock: Callable[[], datetime],
        capacity: int = 1000,
        telemetry: PaperTelemetry | None = None,
    ) -> None:
        if environment != "local":
            raise PaperError("paper_simulator_is_local_only")
        if type(capacity) is not int or not 1 <= capacity <= 1000:
            raise PaperError("invalid_journal_capacity")
        self._initial, self._config = detached(initial_portfolio), detached(config)
        self._ledger = Ledger(account_id, self._initial, self._config)
        # Validate account identifier even before the first journal command.
        self._ledger.snapshot()
        self._risk, self._clock, self._capacity = risk, clock, capacity
        self._telemetry = telemetry or PaperTelemetry()
        self._lock = RLock()
        self._entries: list[PaperJournalEntry] = []
        self._intents: dict[str, str] = {}
        self._market_keys: dict[tuple[str, int], str] = {}
        self._last_now = self._initial.as_of

    def _scope(self, workspace_id: str) -> None:
        if workspace_id != self._initial.workspace_id:
            raise PaperError("workspace_mismatch")

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise PaperError("invalid_clock")
        now = now.astimezone(UTC)
        if now < self._last_now:
            raise PaperError("clock_moved_backwards")
        self._last_now = now
        return now

    def _capacity_check(self) -> None:
        if len(self._entries) >= self._capacity:
            raise PaperError("journal_capacity_exhausted")

    def _commit(self, command: PaperCommand) -> None:
        self._capacity_check()
        with self._telemetry.tracer.start_as_current_span(
            "paper.commit", record_exception=False, set_status_on_exception=False
        ):
            next_ledger = self._ledger.apply(command)
            next_snapshot = detached(next_ledger.snapshot())
            entry = PaperJournalEntry(
                sequence=len(self._entries) + 1,
                previous_hash=self._entries[-1].entry_hash
                if self._entries
                else header_hash(self._ledger.account_id, self._initial, self._config),
                command=command,
                state_hash=content_hash(next_snapshot),
                entry_hash=ZERO_HASH,
            )
            entry = entry.model_copy(update={"entry_hash": entry_hash(entry)})
            proposed_journal = PaperReplay(
                account_id=self._ledger.account_id,
                initial_portfolio=self._initial,
                config=self._config,
                entries=(*self._entries, entry),
            )
            if len(proposed_journal.model_dump_json().encode("utf-8")) > MAX_ARTIFACT_BYTES:
                raise PaperError("journal_size_exhausted")
            previous_fills = sum(len(x.order.fills) for x in self._ledger.orders.values())
            fills = sum(len(x.order.fills) for x in next_ledger.orders.values()) - previous_fills
            # Commit bookkeeping before diagnostic hooks: a lost acknowledgement is reconciled.
            self._entries.append(entry)
            self._ledger = next_ledger
            if command.permit is not None:
                approval = command.permit.approval
                self._intents[approval.order_intent_id] = approval.client_order_id
            if command.book is not None:
                book = command.book
                self._market_keys[(book.instrument_id.value, book.sequence)] = content_hash(book)
            self._telemetry.committed(command.kind, fills)

    def submit(
        self, *, workspace_id: str, order_intent_id: str, fencing_token: int
    ) -> Order | None:
        with self._lock:
            self._scope(workspace_id)
            existing = self._intents.get(order_intent_id)
            if existing is not None:
                return detached(self._ledger.orders[existing].order)
            self._capacity_check()
            if self._ledger.sealed:
                raise PaperError("batch_sealed")
            if not self._ledger.snapshot().portfolio.is_reconciled:
                raise PaperError("reconciliation_required")
            self._now()
            permit = self._risk.handoff(
                workspace_id=workspace_id,
                order_intent_id=order_intent_id,
                fencing_token=fencing_token,
            )
            if permit is None:
                return None
            # Risk's clock may advance while it checks policy. Record submission after issuance.
            self._commit(PaperCommand(kind="submit", at=self._now(), permit=detached(permit)))
            return detached(self._ledger.orders[permit.approval.client_order_id].order)

    def observe(self, *, workspace_id: str, book: PaperBook) -> None:
        book = detached(book)
        with self._lock:
            self._scope(workspace_id)
            key = (book.instrument_id.value, book.sequence)
            if key in self._market_keys:
                if self._market_keys[key] != content_hash(book):
                    raise PaperError("market_idempotency_conflict")
                return
            self._capacity_check()
            now = self._now()
            commands = tuple(
                (item.order.order_intent_id, item.permit.approval.fencing_token)
                for item in self._ledger.orders.values()
                if item.order.status.is_open and item.order.instrument_id == book.instrument_id
            )
            with self._risk.execution_guard(
                workspace_id=workspace_id, commands=commands
            ) as blocked:
                self._commit(
                    PaperCommand(kind="market", at=now, book=book, blocked_intents=blocked)
                )

    def cancel(self, *, workspace_id: str, client_order_id: str) -> Order:
        with self._lock:
            self._scope(workspace_id)
            item = self._ledger.orders.get(client_order_id)
            if item is None:
                raise PaperError("unknown_order")
            if item.order.status.is_open:
                self._commit(
                    PaperCommand(kind="cancel", at=self._now(), client_order_id=client_order_id)
                )
            return detached(self._ledger.orders[client_order_id].order)

    def export_replay(self, *, workspace_id: str) -> PaperReplay:
        with self._lock:
            self._scope(workspace_id)
            return detached(
                PaperReplay(
                    account_id=self._ledger.account_id,
                    initial_portfolio=self._initial,
                    config=self._config,
                    entries=tuple(self._entries),
                )
            )

    def read(self, *, workspace_id: str) -> tuple[int, PaperAccountState]:
        with self._lock:
            self._scope(workspace_id)
            return len(self._entries), detached(self._ledger.snapshot())

    def reconcile(self, *, workspace_id: str) -> tuple[int, PaperAccountState, datetime]:
        with self._lock:
            self._scope(workspace_id)
            state = replay(self.export_replay(workspace_id=workspace_id))
            if content_hash(state) != content_hash(self._ledger.snapshot()):
                raise PaperError("simulator_reconciliation_mismatch")
            return len(self._entries), state, self._now()


class PaperDeliveryUnknown(PaperError):
    """The simulator may have committed; read its journal instead of submitting again."""


class LocalPaperBroker:
    """A disposable broker projection. Recreate over the SAME venue for local crash replay."""

    def __init__(
        self, *, workspace_id: str, venue: LocalPaperVenue, telemetry: PaperTelemetry | None = None
    ) -> None:
        self._workspace_id, self._venue = workspace_id, venue
        self._telemetry = telemetry or PaperTelemetry()
        self._lock = RLock()
        self._sequence, self._state = venue.read(workspace_id=workspace_id)
        self._connected = True

    @property
    def state(self) -> PaperAccountState:
        with self._lock:
            sequence, _ = self._venue.read(workspace_id=self._workspace_id)
            if self._connected and sequence == self._sequence:
                return detached(self._state)
            orders = tuple(
                item.model_copy(update={"status": OrderStatus.UNKNOWN})
                if item.status.is_open
                else item
                for item in self._state.orders
            )
            return detached(
                self._state.model_copy(
                    update={
                        "orders": orders,
                        "portfolio": self._state.portfolio.model_copy(
                            update={"is_reconciled": False}
                        ),
                    }
                )
            )

    def _ack(self, acknowledge: bool) -> None:
        if not acknowledge or not self._connected:
            self._connected = False
            raise PaperDeliveryUnknown("paper_delivery_unknown")
        self._sequence, self._state = self._venue.read(workspace_id=self._workspace_id)
        self._connected = True

    def submit(
        self, *, order_intent_id: str, fencing_token: int, acknowledge: bool = True
    ) -> Order | None:
        with self._lock:
            if not self.state.portfolio.is_reconciled:
                raise PaperError("reconciliation_required")
            try:
                order = self._venue.submit(
                    workspace_id=self._workspace_id,
                    order_intent_id=order_intent_id,
                    fencing_token=fencing_token,
                )
                self._ack(acknowledge)
                return order
            except Exception:
                self._connected = False
                raise

    def observe(self, book: PaperBook, *, acknowledge: bool = True) -> None:
        with self._lock:
            try:
                self._venue.observe(workspace_id=self._workspace_id, book=book)
                self._ack(acknowledge)
            except Exception:
                self._connected = False
                raise

    def cancel(self, client_order_id: str, *, acknowledge: bool = True) -> Order:
        with self._lock:
            try:
                order = self._venue.cancel(
                    workspace_id=self._workspace_id, client_order_id=client_order_id
                )
                self._ack(acknowledge)
                return order
            except Exception:
                self._connected = False
                raise

    def reconcile(self) -> PaperReconciliation:
        with self._lock:
            previous = {fill.fill_id for order in self._state.orders for fill in order.fills}
            sequence, state, now = self._venue.reconcile(workspace_id=self._workspace_id)
            discovered = tuple(
                fill.fill_id
                for order in state.orders
                for fill in order.fills
                if fill.fill_id not in previous
            )
            result = PaperReconciliation(
                sequence=sequence,
                discovered_fill_ids=discovered,
                state_hash=content_hash(state),
                reconciled_at=now,
            )
            self._sequence, self._state, self._connected = sequence, state, True
            self._telemetry.reconciled(len(discovered))
            return result
