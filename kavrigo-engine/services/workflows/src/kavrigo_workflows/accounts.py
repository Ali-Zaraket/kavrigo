"""PostgreSQL paper authority: account row lock, database-time fencing and immutable receipts."""

import json
from datetime import timedelta

import structlog
from opentelemetry import metrics, trace
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from kavrigo_domain import content_hash
from kavrigo_paper.account import detached
from kavrigo_workflows.contracts import (
    AccountCommand,
    AccountDefinition,
    AccountEvent,
    AccountReceipt,
    AccountRef,
    Lease,
)
from kavrigo_workflows.database import MAX_BYTES, EngineDatabase, db_now, encode, row
from kavrigo_workflows.machine import AccountMachine, DurableError


async def outbox(
    connection: AsyncConnection, workspace: str, topic: str, identity: str, payload: str
) -> None:
    await connection.execute(
        text("""INSERT INTO kavrigo.engine_outbox
        (workspace_id, event_id, topic, payload, created_at)
        VALUES (:ws, :id, :topic, :payload, clock_timestamp()) ON CONFLICT DO NOTHING"""),
        {"ws": workspace, "id": identity, "topic": topic, "payload": payload},
    )


class AccountRepository:
    def __init__(self, database: EngineDatabase) -> None:
        self.db = database
        self.tracer = trace.get_tracer("kavrigo.durable.account")
        self.counter = metrics.get_meter("kavrigo.durable.account").create_counter(
            "kavrigo.account.commands"
        )
        self.log = structlog.get_logger(__name__)

    async def create(self, definition: AccountDefinition) -> AccountReceipt:
        definition = detached(definition)
        machine = AccountMachine(definition)
        receipt = machine.initial_receipt()
        encoded, receipt_json = encode(definition), encode(receipt)
        size = len((encoded + receipt_json).encode("utf-8"))
        if size > MAX_BYTES:
            raise DurableError("account_capacity_exhausted")
        ref = AccountRef(workspace_id=machine.workspace_id, account_id=definition.account_id)
        async with self.db.transaction(ref.workspace_id) as connection:
            await connection.execute(
                text("""INSERT INTO kavrigo.engine_accounts
                (workspace_id, account_id, definition, definition_hash, head_sequence, head_hash, head_receipt, bytes_used)
                VALUES (:ws, :account, :definition, :hash, 0, :hash, :receipt, :size)
                ON CONFLICT DO NOTHING"""),
                {
                    "ws": ref.workspace_id,
                    "account": ref.account_id,
                    "definition": encoded,
                    "hash": content_hash(definition),
                    "receipt": receipt_json,
                    "size": size,
                },
            )
            existing = await self._account(connection, ref, lock=True)
            if existing["definition_hash"] != content_hash(definition):
                raise DurableError("account_definition_conflict")
            return AccountReceipt.model_validate_json(existing["head_receipt"])

    async def _account(
        self, connection: AsyncConnection, ref: AccountRef, *, lock: bool = False
    ) -> RowMapping:
        sql = "SELECT * FROM kavrigo.engine_accounts WHERE workspace_id=:ws AND account_id=:account"
        if lock:
            sql += " FOR UPDATE"
        result = await row(connection, sql, {"ws": ref.workspace_id, "account": ref.account_id})
        if result is None:
            raise DurableError("account_not_found")
        return result

    async def acquire(self, ref: AccountRef, owner: str, *, seconds: int = 30) -> Lease:
        if type(seconds) is not int or not 1 <= seconds <= 300:
            raise DurableError("invalid_lease_duration")
        # Validate owner before touching the database; expiry/token are assigned below.
        async with self.db.transaction(ref.workspace_id) as connection:
            account = await self._account(connection, ref, lock=True)
            now = await db_now(connection)
            active = account["lease_until"] is not None and account["lease_until"] > now
            if active and account["lease_owner"] != owner:
                raise DurableError("account_lease_busy")
            token = account["lease_token"] if active else account["lease_token"] + 1
            lease = Lease(
                **ref.model_dump(),
                owner=owner,
                token=token,
                expires_at=now + timedelta(seconds=seconds),
            )
            await connection.execute(
                text("""UPDATE kavrigo.engine_accounts SET
                lease_owner=:owner, lease_token=:token, lease_until=:until
                WHERE workspace_id=:ws AND account_id=:account"""),
                {
                    "owner": owner,
                    "token": token,
                    "until": lease.expires_at,
                    "ws": ref.workspace_id,
                    "account": ref.account_id,
                },
            )
            return lease

    async def release(self, lease: Lease) -> None:
        async with self.db.transaction(lease.workspace_id) as connection:
            await connection.execute(
                text("""UPDATE kavrigo.engine_accounts SET lease_until=clock_timestamp()
                WHERE workspace_id=:ws AND account_id=:account AND lease_owner=:owner AND lease_token=:token"""),
                {
                    "ws": lease.workspace_id,
                    "account": lease.account_id,
                    "owner": lease.owner,
                    "token": lease.token,
                },
            )

    async def _machine(
        self, connection: AsyncConnection, ref: AccountRef, account: RowMapping
    ) -> AccountMachine:
        definition = AccountDefinition.model_validate_json(account["definition"])
        if content_hash(definition) != account["definition_hash"]:
            raise DurableError("account_definition_corrupt")
        rows = (
            (
                await connection.execute(
                    text("""SELECT sequence, command, request_hash, state_hash, occurred_at
            FROM kavrigo.engine_commands WHERE workspace_id=:ws AND account_id=:account ORDER BY sequence"""),
                    {"ws": ref.workspace_id, "account": ref.account_id},
                )
            )
            .mappings()
            .all()
        )
        events = []
        for record in rows:
            command = AccountCommand.model_validate_json(record["command"])
            if content_hash(command) != record["request_hash"]:
                raise DurableError("account_command_corrupt")
            events.append(
                AccountEvent(
                    sequence=record["sequence"],
                    command=command,
                    occurred_at=record["occurred_at"],
                    state_hash=record["state_hash"],
                )
            )
        machine = AccountMachine.reconstruct(definition, tuple(events))
        if machine.sequence != account["head_sequence"] or machine.chain != account["head_hash"]:
            raise DurableError("account_head_mismatch")
        saved = AccountReceipt.model_validate_json(account["head_receipt"])
        if saved.state != machine.ledger.snapshot() or saved.state_hash != machine.chain:
            raise DurableError("account_projection_mismatch")
        return machine

    async def read(self, ref: AccountRef) -> AccountReceipt:
        async with self.db.transaction(ref.workspace_id) as connection:
            account = await self._account(connection, ref, lock=True)
            await self._machine(connection, ref, account)
            return AccountReceipt.model_validate_json(account["head_receipt"])

    async def commit(self, lease: Lease, command: AccountCommand) -> AccountReceipt:
        command = detached(command)
        with self.tracer.start_as_current_span(
            "account.command", record_exception=False, set_status_on_exception=False
        ):
            async with self.db.transaction(lease.workspace_id) as connection:
                result, replayed = await self.commit_in_transaction(connection, lease, command)
        # The transaction has committed before diagnostics/acknowledgement. Retry the same key
        # on ANY uncertain failure here; the retained receipt is authoritative.
        self.counter.add(1, {"kind": command.kind, "replayed": replayed})
        self.log.info("account_command", kind=command.kind, replayed=replayed)
        return result

    async def commit_in_transaction(
        self,
        connection: AsyncConnection,
        lease: Lease,
        command: AccountCommand,
    ) -> tuple[AccountReceipt, bool]:
        account = await self._account(connection, lease, lock=True)
        params = {"ws": lease.workspace_id, "account": lease.account_id, "key": command.key}
        existing = await row(
            connection,
            """SELECT request_hash, receipt FROM kavrigo.engine_commands
            WHERE workspace_id=:ws AND account_id=:account AND command_key=:key""",
            params,
        )
        if existing is not None:
            if existing["request_hash"] != content_hash(command):
                raise DurableError("command_idempotency_conflict")
            return AccountReceipt.model_validate_json(existing["receipt"]), True
        if command.book is not None:
            existing = await row(
                connection,
                """SELECT market_hash, receipt FROM kavrigo.engine_commands
                WHERE workspace_id=:ws AND account_id=:account AND market_instrument=:instrument AND market_sequence=:seq""",
                {
                    **params,
                    "instrument": command.book.instrument_id.value,
                    "seq": command.book.sequence,
                },
            )
            if existing is not None:
                if existing["market_hash"] != content_hash(command.book):
                    raise DurableError("market_idempotency_conflict")
                return AccountReceipt.model_validate_json(existing["receipt"]), True
        now = await db_now(connection)
        if (
            account["lease_token"] != lease.token
            or account["lease_owner"] != lease.owner
            or account["lease_until"] is None
            or now >= min(account["lease_until"], lease.expires_at)
        ):
            raise DurableError("stale_execution_lease")
        if account["head_sequence"] >= 1000:
            raise DurableError("account_capacity_exhausted")
        machine = await self._machine(connection, lease, account)
        now = await db_now(connection)
        result = machine.apply(command, now)
        encoded, receipt_json = encode(command), encode(result)
        # Retain every historical receipt and command. Account projection replaces its prior
        # copy, so count only its positive growth in addition to the new immutable receipt.
        growth = max(
            0, len(receipt_json.encode("utf-8")) - len(account["head_receipt"].encode("utf-8"))
        )
        size = account["bytes_used"] + len((encoded + receipt_json).encode("utf-8")) + growth
        if size > MAX_BYTES:
            raise DurableError("account_capacity_exhausted")
        if await db_now(connection) >= min(account["lease_until"], lease.expires_at):
            raise DurableError("lease_expired_during_command")
        await connection.execute(
            text("""INSERT INTO kavrigo.engine_commands
            (workspace_id, account_id, sequence, command_key, command, request_hash, receipt, state_hash,
             occurred_at, lease_token, market_instrument, market_sequence, market_hash)
            VALUES (:ws, :account, :sequence, :key, :command, :request_hash, :receipt, :state_hash,
                :at, :token, :instrument, :market_sequence, :market_hash)"""),
            {
                **params,
                "sequence": result.sequence,
                "command": encoded,
                "request_hash": content_hash(command),
                "receipt": receipt_json,
                "state_hash": result.state_hash,
                "at": now,
                "token": lease.token,
                "instrument": command.book.instrument_id.value if command.book else None,
                "market_sequence": command.book.sequence if command.book else None,
                "market_hash": content_hash(command.book) if command.book else None,
            },
        )
        await connection.execute(
            text("""UPDATE kavrigo.engine_accounts SET head_sequence=:seq,
            head_hash=:hash, head_receipt=:receipt, bytes_used=:size
            WHERE workspace_id=:ws AND account_id=:account"""),
            {
                **params,
                "seq": result.sequence,
                "hash": result.state_hash,
                "receipt": receipt_json,
                "size": size,
            },
        )
        await outbox(
            connection,
            lease.workspace_id,
            "account.updated",
            "evt_" + content_hash({"account": lease.account_id, "seq": result.sequence})[7:],
            json.dumps(
                {
                    "account_id": lease.account_id,
                    "sequence": result.sequence,
                    "state_hash": result.state_hash,
                }
            ),
        )
        if await db_now(connection) >= min(account["lease_until"], lease.expires_at):
            raise DurableError("lease_expired_during_command")
        return result, False
