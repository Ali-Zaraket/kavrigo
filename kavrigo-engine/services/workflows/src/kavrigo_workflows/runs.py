"""Durable frozen run inputs and stage receipts. Unknown model dispatch is never repeated."""

import json
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from kavrigo_domain import DomainModel, content_hash
from kavrigo_paper.account import detached
from kavrigo_workflows.accounts import outbox
from kavrigo_workflows.contracts import RunDefinition, RunRef, StageRef
from kavrigo_workflows.database import EngineDatabase, encode, row
from kavrigo_workflows.machine import DurableError


class RunRepository:
    def __init__(self, database: EngineDatabase) -> None:
        self.db = database

    async def create(self, definition: RunDefinition) -> RunRef:
        definition = detached(definition)
        ref = RunRef(
            workspace_id=definition.workspace_id,
            run_id=definition.run_id,
            input_hash=content_hash(definition),
        )
        async with self.db.transaction(ref.workspace_id) as connection:
            await connection.execute(
                text("""INSERT INTO kavrigo.engine_runs
                (workspace_id, run_id, definition, input_hash, created_at) VALUES (:ws,:run,:definition,:hash,clock_timestamp())
                ON CONFLICT DO NOTHING"""),
                {
                    "ws": ref.workspace_id,
                    "run": ref.run_id,
                    "definition": encode(definition),
                    "hash": ref.input_hash,
                },
            )
            await self.load_in_transaction(connection, ref)
            await outbox(connection, ref.workspace_id, "run.queued", ref.run_id, encode(ref))
        return ref

    async def load_in_transaction(
        self, connection: AsyncConnection, ref: RunRef, *, lock: bool = False
    ) -> RunDefinition:
        sql = "SELECT definition, input_hash FROM kavrigo.engine_runs WHERE workspace_id=:ws AND run_id=:run"
        if lock:
            sql += " FOR UPDATE"
        found = await row(connection, sql, {"ws": ref.workspace_id, "run": ref.run_id})
        if found is None:
            raise DurableError("run_not_found")
        definition = RunDefinition.model_validate_json(found["definition"])
        if ref.input_hash != found["input_hash"] or content_hash(definition) != ref.input_hash:
            raise DurableError("run_input_conflict")
        return definition

    async def load(self, ref: RunRef) -> RunDefinition:
        async with self.db.transaction(ref.workspace_id) as connection:
            return await self.load_in_transaction(connection, ref)

    async def stage(self, connection: AsyncConnection, ref: RunRef, name: str) -> RowMapping | None:
        return await row(
            connection,
            """SELECT * FROM kavrigo.engine_steps
            WHERE workspace_id=:ws AND run_id=:run AND stage=:stage""",
            {"ws": ref.workspace_id, "run": ref.run_id, "stage": name},
        )

    @staticmethod
    def stage_ref(ref: RunRef, saved: RowMapping) -> StageRef:
        if saved["status"] == "started":
            raise DurableError("stage_dispatch_uncertain")
        if saved["input_hash"] != ref.input_hash or saved["output"] is None:
            raise DurableError("stage_receipt_corrupt")
        # Output is JSON with exact decimal strings; its hash is verified on every lookup.
        if content_hash(json.loads(saved["output"])) != saved["output_hash"]:
            raise DurableError("stage_output_corrupt")
        return StageRef(
            **ref.model_dump(),
            stage=saved["stage"],
            output_hash=saved["output_hash"],
            status=saved["status"],
        )

    async def claim_dispatch(self, ref: RunRef, name: str, attempt: str) -> StageRef | None:
        async with self.db.transaction(ref.workspace_id) as connection:
            await self.load_in_transaction(connection, ref, lock=True)
            previous = await self.stage(connection, ref, name)
            if previous is not None:
                if previous["status"] == "started":
                    return await self.finish_stage(
                        connection,
                        ref,
                        name,
                        {"reason": "model_dispatch_uncertain"},
                        status="uncertain",
                        attempt=previous["attempt_id"],
                    )
                return self.stage_ref(ref, previous)
            await connection.execute(
                text("""INSERT INTO kavrigo.engine_steps
                (workspace_id,run_id,stage,status,attempt_id,input_hash,started_at)
                VALUES (:ws,:run,:stage,'started',:attempt,:hash,clock_timestamp())"""),
                {
                    "ws": ref.workspace_id,
                    "run": ref.run_id,
                    "stage": name,
                    "attempt": attempt,
                    "hash": ref.input_hash,
                },
            )
            return None

    async def finish_stage(
        self,
        connection: AsyncConnection,
        ref: RunRef,
        name: str,
        output: DomainModel | dict[str, object],
        *,
        status: Literal["completed", "refused", "uncertain"] = "completed",
        attempt: str = "transactional",
    ) -> StageRef:
        # Hash the persisted JSON representation, not a Python model that hashes Decimals as numbers.
        encoded = (
            encode(output)
            if isinstance(output, DomainModel)
            else json.dumps(output, sort_keys=True)
        )
        output_hash = content_hash(json.loads(encoded))
        if len(encoded.encode("utf-8")) > 10_000_000:
            raise DurableError("stage_output_too_large")
        previous = await self.stage(connection, ref, name)
        if previous is not None:
            if previous["status"] != "started":
                return self.stage_ref(ref, previous)
            if previous["attempt_id"] != attempt:
                raise DurableError("stage_attempt_fenced")
            await connection.execute(
                text("""UPDATE kavrigo.engine_steps SET status=:status, output=:output,
                output_hash=:output_hash, finished_at=clock_timestamp()
                WHERE workspace_id=:ws AND run_id=:run AND stage=:stage AND status='started' AND attempt_id=:attempt"""),
                {
                    "ws": ref.workspace_id,
                    "run": ref.run_id,
                    "stage": name,
                    "attempt": attempt,
                    "status": status,
                    "output": encoded,
                    "output_hash": output_hash,
                },
            )
        else:
            await connection.execute(
                text("""INSERT INTO kavrigo.engine_steps
                (workspace_id,run_id,stage,status,attempt_id,input_hash,output,output_hash,started_at,finished_at)
                VALUES (:ws,:run,:stage,:status,:attempt,:hash,:output,:output_hash,clock_timestamp(),clock_timestamp())"""),
                {
                    "ws": ref.workspace_id,
                    "run": ref.run_id,
                    "stage": name,
                    "attempt": attempt,
                    "hash": ref.input_hash,
                    "status": status,
                    "output": encoded,
                    "output_hash": output_hash,
                },
            )
        return StageRef(**ref.model_dump(), stage=name, output_hash=output_hash, status=status)

    async def finish_run(self, ref: RunRef) -> StageRef:
        async with self.db.transaction(ref.workspace_id) as connection:
            definition = await self.load_in_transaction(connection, ref, lock=True)
            saved = await row(
                connection,
                """SELECT final_receipt FROM kavrigo.engine_runs
                WHERE workspace_id=:ws AND run_id=:run""",
                {"ws": ref.workspace_id, "run": ref.run_id},
            )
            assert saved is not None
            if saved["final_receipt"] is not None:
                return StageRef.model_validate_json(saved["final_receipt"])
            stages = (
                (
                    await connection.execute(
                        text("""SELECT stage, status, output_hash FROM kavrigo.engine_steps
                WHERE workspace_id=:ws AND run_id=:run ORDER BY stage"""),
                        {"ws": ref.workspace_id, "run": ref.run_id},
                    )
                )
                .mappings()
                .all()
            )
            if not stages:
                raise DurableError("run_has_no_results")
            by_name = {s["stage"]: s["status"] for s in stages}
            required = {
                "agent": "evaluate",
                "backtest": "backtest",
                "health": "health",
                "supervision": "supervise.0",
            }[definition.job.kind]
            if required not in by_name:
                raise DurableError("run_missing_required_stage")
            if (
                definition.job.kind == "agent"
                and by_name["evaluate"] == "completed"
                and "execute" not in by_name
            ):
                raise DurableError("run_missing_execution_stage")
            if (
                definition.job.kind == "supervision"
                and all(s == "completed" for s in by_name.values())
                and any(
                    f"supervise.{index}" not in by_name for index in range(definition.job.cycles)
                )
            ):
                raise DurableError("run_missing_supervision_stage")
            status: Literal["completed", "refused", "uncertain"] = "completed"
            if any(s["status"] in ("started", "uncertain") for s in stages):
                status = "uncertain"
            elif any(s["status"] == "refused" for s in stages):
                status = "refused"
            result = await self.finish_stage(
                connection, ref, "finish", {"stages": [dict(s) for s in stages]}, status=status
            )
            await connection.execute(
                text("""UPDATE kavrigo.engine_runs SET status=:status, final_receipt=:receipt
                WHERE workspace_id=:ws AND run_id=:run"""),
                {
                    "ws": ref.workspace_id,
                    "run": ref.run_id,
                    "status": status,
                    "receipt": encode(result),
                },
            )
            await outbox(
                connection,
                ref.workspace_id,
                "run.finished",
                "finished-" + ref.run_id,
                encode(result),
            )
            return result
