"""Database-enforced tenant isolation and immutability.

These tests exist because the guarantees they check are not observable from application code.
An application that filters correctly today can stop filtering correctly tomorrow; these assert
that the database refuses regardless.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from kavrigo_api.db.session import Database
from kavrigo_api.repositories.agents import AgentRepository
from kavrigo_api.repositories.identity import IdentityRepository

pytestmark = pytest.mark.integration


def _hash() -> str:
    return "sha256:" + "ab" * 32


async def _seed_workspace(database: Database, slug: str) -> tuple[str, str]:
    """Create a user and a workspace they own. Returns (workspace_id, user_id)."""
    async with database.global_session() as session:
        repo = IdentityRepository(session)
        user = await repo.ensure_user(external_id=f"ext_{slug}", email=f"{slug}@example.test")
        workspace = await repo.create_workspace(
            name=slug.title(), slug=slug, owner_user_id=user.user_id
        )
        return workspace.workspace_id, user.user_id


async def _seed_agent(database: Database, workspace_id: str, name: str) -> str:
    async with database.workspace_session(workspace_id) as session:
        repo = AgentRepository(session, workspace_id)
        agent = await repo.create_agent(name=name, description="", created_by="usr_seed")
        await repo.insert_version(
            agent_id=agent.agent_id,
            version=1,
            spec={"name": name},
            spec_hash=_hash(),
            prompt_version_id=f"pv_{uuid.uuid4().hex}",
            prompt_hash=_hash(),
            feature_set_version="v1",
            created_by="usr_seed",
            author_kind="human",
            change_summary="seed",
        )
        await repo.set_current_version(agent.agent_id, 1)
        return agent.agent_id


class TestApplicationRolePrivileges:
    """RLS is meaningless if the application connects as a superuser."""

    async def test_the_application_role_cannot_bypass_rls(self, database: Database) -> None:
        async with database.global_session() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
                        "FROM pg_roles WHERE rolname = current_user"
                    )
                )
            ).one()
        assert row.rolsuper is False, "the application must not connect as a superuser"
        assert row.rolbypassrls is False, "the application must not have BYPASSRLS"
        assert row.rolcreatedb is False
        assert row.rolcreaterole is False

    async def test_the_application_role_cannot_disable_row_level_security(
        self, database: Database
    ) -> None:
        """It must not be able to switch off its own containment."""
        with pytest.raises((ProgrammingError, DBAPIError)):
            async with database.global_session() as session:
                await session.execute(text("ALTER TABLE kavrigo.agents DISABLE ROW LEVEL SECURITY"))

    async def test_the_application_role_cannot_truncate_the_audit_trail(
        self, database: Database
    ) -> None:
        with pytest.raises((ProgrammingError, DBAPIError)):
            async with database.global_session() as session:
                await session.execute(text("TRUNCATE kavrigo.audit_events"))


class TestSchemaInvariants:
    """Catch a future table that forgets its isolation, rather than discovering it later."""

    async def test_every_table_with_a_workspace_id_has_rls_enabled_and_forced(
        self, database: Database
    ) -> None:
        async with database.global_session() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT c.relname AS table_name, c.relrowsecurity, c.relforcerowsecurity
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'kavrigo'
                          AND c.relkind = 'r'
                          AND EXISTS (
                              SELECT 1 FROM pg_attribute a
                              WHERE a.attrelid = c.oid
                                AND a.attname = 'workspace_id'
                                AND a.attnum > 0
                                AND NOT a.attisdropped
                          )
                        """
                    )
                )
            ).all()

        assert rows, "expected at least one tenant-scoped table"
        unprotected = [
            r.table_name for r in rows if not (r.relrowsecurity and r.relforcerowsecurity)
        ]
        assert unprotected == [], (
            f"tables with a workspace_id but no forced RLS: {unprotected}. "
            "Add ENABLE + FORCE ROW LEVEL SECURITY and an isolation policy in the migration."
        )

    async def test_the_declared_list_matches_the_database(self, database: Database) -> None:
        """``TENANT_SCOPED_TABLES`` in db/models.py is documentation unless it is checked."""
        from kavrigo_api.db.models import ENGINE_TABLES, SELF_POLICIED_TABLES, TENANT_SCOPED_TABLES

        async with database.global_session() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT c.relname FROM pg_class c "
                            "JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "WHERE n.nspname = 'kavrigo' AND c.relkind = 'r' "
                            "AND c.relrowsecurity AND c.relforcerowsecurity"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert set(rows) == set(TENANT_SCOPED_TABLES) | set(SELF_POLICIED_TABLES) | set(
            ENGINE_TABLES
        )

    async def test_append_only_tables_have_their_trigger(self, database: Database) -> None:
        from kavrigo_api.db.models import APPEND_ONLY_TABLES

        async with database.global_session() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT c.relname FROM pg_trigger t "
                            "JOIN pg_class c ON c.oid = t.tgrelid "
                            "JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "JOIN pg_proc p ON p.oid = t.tgfoid "
                            "WHERE n.nspname = 'kavrigo' AND NOT t.tgisinternal "
                            "AND p.proname = 'refuse_mutation'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert set(rows) == set(APPEND_ONLY_TABLES)

    async def test_engine_record_guards_cover_every_mutable_projection(
        self, database: Database
    ) -> None:
        from kavrigo_api.db.models import ENGINE_PROTECTED_RECORD_TABLES

        async with database.global_session() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                            "JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid "
                            "WHERE n.nspname='kavrigo' AND NOT t.tgisinternal AND p.proname='protect_engine_record'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert set(rows) == set(ENGINE_PROTECTED_RECORD_TABLES)


class TestTenantIsolation:
    async def test_a_workspace_cannot_read_another_workspaces_agents(
        self, database: Database
    ) -> None:
        ws_a, _ = await _seed_workspace(database, "alpha")
        ws_b, _ = await _seed_workspace(database, "bravo")
        await _seed_agent(database, ws_a, "alpha-agent")
        await _seed_agent(database, ws_b, "bravo-agent")

        async with database.workspace_session(ws_a) as session:
            visible = await AgentRepository(session, ws_a).list_agents(limit=100)
        assert [a.name for a in visible] == ["alpha-agent"]

    async def test_an_unscoped_query_still_sees_only_its_own_workspace(
        self, database: Database
    ) -> None:
        """The point of RLS: a query that forgets its predicate returns nothing extra."""
        ws_a, _ = await _seed_workspace(database, "charlie")
        ws_b, _ = await _seed_workspace(database, "delta")
        await _seed_agent(database, ws_a, "charlie-agent")
        await _seed_agent(database, ws_b, "delta-agent")

        async with database.workspace_session(ws_a) as session:
            rows = (
                await session.execute(text("SELECT workspace_id, name FROM kavrigo.agents"))
            ).all()
        assert {r.workspace_id for r in rows} == {ws_a}

    async def test_an_unset_workspace_sees_nothing(self, database: Database) -> None:
        """Fail closed: no workspace set means no rows, not all rows."""
        ws_a, _ = await _seed_workspace(database, "echo")
        await _seed_agent(database, ws_a, "echo-agent")

        async with database.global_session() as session:
            rows = (await session.execute(text("SELECT * FROM kavrigo.agents"))).all()
        assert rows == []

    async def test_a_workspace_cannot_write_rows_for_another_workspace(
        self, database: Database
    ) -> None:
        """The policy's WITH CHECK clause, not just its USING clause."""
        ws_a, _ = await _seed_workspace(database, "foxtrot")
        ws_b, _ = await _seed_workspace(database, "golf")

        with pytest.raises((ProgrammingError, DBAPIError)):
            async with database.workspace_session(ws_a) as session:
                await session.execute(
                    text(
                        "INSERT INTO kavrigo.agents "
                        "(agent_id, workspace_id, name, description, current_version, created_by) "
                        "VALUES (:aid, :ws, 'smuggled', '', 0, 'usr_x')"
                    ),
                    {"aid": f"ag_{uuid.uuid4().hex}", "ws": ws_b},
                )

    async def test_a_pooled_connection_does_not_leak_the_previous_workspace(
        self, database: Database
    ) -> None:
        """``set_config(..., is_local => true)`` binds the setting to the transaction.

        Without that, a recycled pooled connection would carry one request's workspace into the
        next — a cross-tenant read that no application code could detect.
        """
        ws_a, _ = await _seed_workspace(database, "hotel")
        await _seed_agent(database, ws_a, "hotel-agent")

        async with database.workspace_session(ws_a) as session:
            assert (
                await session.execute(text("SELECT count(*) FROM kavrigo.agents"))
            ).scalar_one() == 1

        # A later transaction on the same pool with no workspace set must see nothing.
        async with database.global_session() as session:
            assert (
                await session.execute(text("SELECT count(*) FROM kavrigo.agents"))
            ).scalar_one() == 0


class TestImmutability:
    async def test_agent_versions_cannot_be_updated(self, database: Database) -> None:
        ws, _ = await _seed_workspace(database, "india")
        agent_id = await _seed_agent(database, ws, "india-agent")

        with pytest.raises((ProgrammingError, DBAPIError)) as exc:
            async with database.workspace_session(ws) as session:
                await session.execute(
                    text(
                        "UPDATE kavrigo.agent_versions SET change_summary = 'rewritten' "
                        "WHERE agent_id = :aid"
                    ),
                    {"aid": agent_id},
                )
        assert "append-only" in str(exc.value)

    async def test_agent_versions_cannot_be_deleted(self, database: Database) -> None:
        ws, _ = await _seed_workspace(database, "juliett")
        agent_id = await _seed_agent(database, ws, "juliett-agent")

        with pytest.raises((ProgrammingError, DBAPIError)):
            async with database.workspace_session(ws) as session:
                await session.execute(
                    text("DELETE FROM kavrigo.agent_versions WHERE agent_id = :aid"),
                    {"aid": agent_id},
                )

    async def test_audit_events_cannot_be_rewritten(self, database: Database) -> None:
        ws, _ = await _seed_workspace(database, "kilo")
        from kavrigo_api.repositories.audit import AuditRepository

        async with database.workspace_session(ws) as session:
            await AuditRepository(session, ws).record(
                action="test_action", actor="usr_seed", reason="because"
            )

        with pytest.raises((ProgrammingError, DBAPIError)):
            async with database.workspace_session(ws) as session:
                await session.execute(
                    text("UPDATE kavrigo.audit_events SET reason = 'nothing happened'")
                )

    async def test_a_version_cannot_be_attached_to_another_workspaces_agent(
        self, database: Database
    ) -> None:
        """The composite foreign key, not just the RLS policy."""
        ws_a, _ = await _seed_workspace(database, "lima")
        ws_b, _ = await _seed_workspace(database, "mike")
        agent_a = await _seed_agent(database, ws_a, "lima-agent")

        with pytest.raises((ProgrammingError, DBAPIError)):
            async with database.workspace_session(ws_b) as session:
                await AgentRepository(session, ws_b).insert_version(
                    agent_id=agent_a,
                    version=2,
                    spec={},
                    spec_hash=_hash(),
                    prompt_version_id=f"pv_{uuid.uuid4().hex}",
                    prompt_hash=_hash(),
                    feature_set_version="v1",
                    created_by="usr_attacker",
                    author_kind="human",
                    change_summary="cross-tenant",
                )
