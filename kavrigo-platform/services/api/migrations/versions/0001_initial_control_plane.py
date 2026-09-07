"""Initial control plane: users, workspaces, memberships, agents, versions, idempotency, audit.

Revision ID: 0001
Revises:
Created: 2026-09-04

Establishes the three database-enforced guarantees the control plane rests on:

1. **Tenant isolation** — row-level security, ENABLEd and FORCEd, on every tenant-scoped table.
   FORCE matters: without it the table owner bypasses its own policies, so a migration run and
   an application query would disagree about what is visible.
2. **Immutability** — triggers refusing UPDATE and DELETE on ``agent_versions`` and
   ``audit_events``. A version that can be edited is not a version.
3. **Least privilege** — the application role gets DML only, never DDL, and is never the table
   owner.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "kavrigo"
APP_ROLE = "kavrigo_app"

TENANT_SCOPED_TABLES = (
    "memberships",
    "agents",
    "agent_versions",
    "idempotency_keys",
    "audit_events",
)
APPEND_ONLY_TABLES = ("agent_versions", "audit_events")


# The "ck" naming convention is `ck_%(table_name)s_%(constraint_name)s`, so it wraps an
# explicitly-given name. Constraint names below are therefore bare (`user_id_format`), matching
# db/models.py — passing an already-prefixed name yields `ck_users_ck_users_user_id_format` and
# makes the migration disagree with the models on every autogenerate.


def _timestamp(name: str, *, nullable: bool = False, default: bool = False) -> sa.Column[object]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if default else None,
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # ------------------------------------------------------------------ users
    # Global, not tenant-scoped: one account can belong to several workspaces.
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("external_id", sa.String(128), nullable=False, unique=True),
        sa.Column("email", sa.String(320)),
        _timestamp("created_at", default=True),
        _timestamp("last_seen_at", nullable=True),
        sa.CheckConstraint(r"user_id ~ '^usr_[0-9a-f]{32}$'", name="user_id_format"),
        schema=SCHEMA,
    )

    # ------------------------------------------------------------- workspaces
    op.create_table(
        "workspaces",
        sa.Column("workspace_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        _timestamp("created_at", default=True),
        _timestamp("archived_at", nullable=True),
        sa.CheckConstraint(r"workspace_id ~ '^ws_[0-9a-f]{32}$'", name="workspace_id_format"),
        sa.CheckConstraint(r"slug ~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$'", name="slug_format"),
        schema=SCHEMA,
    )

    # ------------------------------------------------------------ memberships
    op.create_table(
        "memberships",
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.workspaces.workspace_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        _timestamp("created_at", default=True),
        sa.CheckConstraint("role IN ('owner','admin','member','viewer')", name="role_valid"),
        schema=SCHEMA,
    )
    op.create_index("ix_memberships_user", "memberships", ["user_id"], schema=SCHEMA)

    # ----------------------------------------------------------------- agents
    op.create_table(
        "agents",
        sa.Column("agent_id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.workspaces.workspace_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("current_version", sa.Integer, nullable=False, server_default="0"),
        _timestamp("created_at", default=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        _timestamp("archived_at", nullable=True),
        sa.CheckConstraint(r"agent_id ~ '^ag_[0-9a-f]{32}$'", name="agent_id_format"),
        sa.CheckConstraint(r"name ~ '^[a-z0-9][a-z0-9-]*$'", name="name_format"),
        sa.CheckConstraint("current_version >= 0", name="current_version_non_negative"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_agents_workspace_name"),
        # Required so agent_versions can reference (agent_id, workspace_id) together, which is
        # what prevents a version being attached to an agent in a different workspace.
        sa.UniqueConstraint("agent_id", "workspace_id", name="uq_agents_id_workspace"),
        schema=SCHEMA,
    )

    # --------------------------------------------------------- agent_versions
    op.create_table(
        "agent_versions",
        sa.Column("agent_version_id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("spec", postgresql.JSONB, nullable=False),
        sa.Column("spec_hash", sa.String(71), nullable=False),
        sa.Column("prompt_version_id", sa.String(36), nullable=False),
        sa.Column("prompt_hash", sa.String(71), nullable=False),
        sa.Column("feature_set_version", sa.String(32), nullable=False),
        _timestamp("created_at", default=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("author_kind", sa.String(16), nullable=False, server_default="human"),
        sa.Column("change_summary", sa.Text, nullable=False, server_default=""),
        sa.Column("stage", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("approval_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "approved_environments",
            postgresql.ARRAY(sa.String(32)),
            nullable=False,
            server_default="{}",
        ),
        sa.CheckConstraint(r"agent_version_id ~ '^av_[0-9a-f]{32}$'", name="version_id_format"),
        sa.CheckConstraint(r"spec_hash ~ '^sha256:[0-9a-f]{64}$'", name="spec_hash_format"),
        sa.CheckConstraint(r"prompt_hash ~ '^sha256:[0-9a-f]{64}$'", name="prompt_hash_format"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint(
            "author_kind IN ('human','ai_assisted','ai_generated')",
            name="author_kind_valid",
        ),
        sa.CheckConstraint(
            "approval_status IN ('pending','approved','rejected','withdrawn')",
            name="approval_status_valid",
        ),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
        sa.ForeignKeyConstraint(
            ["agent_id", "workspace_id"],
            [f"{SCHEMA}.agents.agent_id", f"{SCHEMA}.agents.workspace_id"],
            ondelete="CASCADE",
            name="fk_agent_versions_agent",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_agent_versions_workspace_agent",
        "agent_versions",
        ["workspace_id", "agent_id", "version"],
        schema=SCHEMA,
    )

    # -------------------------------------------------------- idempotency keys
    op.create_table(
        "idempotency_keys",
        sa.Column("workspace_id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), primary_key=True),
        sa.Column("endpoint", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(71), nullable=False),
        sa.Column("response_status", sa.Integer, nullable=False),
        sa.Column("response_body", postgresql.JSONB, nullable=False),
        _timestamp("created_at", default=True),
        _timestamp("expires_at"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_idempotency_keys_expires", "idempotency_keys", ["expires_at"], schema=SCHEMA
    )

    # ----------------------------------------------------------- audit events
    op.create_table(
        "audit_events",
        sa.Column("audit_id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        _timestamp("created_at", default=True),
        sa.Column("subject_type", sa.String(64)),
        sa.Column("subject_id", sa.String(64)),
        sa.Column("request_id", sa.String(64)),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_workspace_created",
        "audit_events",
        ["workspace_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_subject",
        "audit_events",
        ["workspace_id", "subject_type", "subject_id"],
        schema=SCHEMA,
    )

    _install_row_level_security()
    _install_append_only_triggers()
    _grant_application_privileges()


def _install_row_level_security() -> None:
    """Enable, FORCE and police tenant isolation on every tenant-scoped table.

    ``current_setting(..., true)`` returns NULL when the variable is unset, and ``NULL = x`` is
    NULL rather than true — so a connection that forgets to set the workspace sees no rows
    instead of every row. Fail closed.
    """
    for table in TENANT_SCOPED_TABLES:
        qualified = f"{SCHEMA}.{table}"
        op.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_workspace_isolation ON {qualified}
              USING (workspace_id = current_setting('kavrigo.workspace_id', true))
              WITH CHECK (workspace_id = current_setting('kavrigo.workspace_id', true))
            """
        )

    # The workspace registry is protected too. Without this, a query that forgot to join through
    # memberships could enumerate every tenant's name and slug. It needs its own policy rather
    # than the standard one because listing a user's workspaces happens before any workspace has
    # been chosen — so membership, keyed on kavrigo.user_id, is the second visibility path.
    op.execute(f"ALTER TABLE {SCHEMA}.workspaces ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.workspaces FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY workspaces_visibility ON {SCHEMA}.workspaces
          FOR SELECT
          USING (
            workspace_id = current_setting('kavrigo.workspace_id', true)
            OR EXISTS (
              SELECT 1 FROM {SCHEMA}.memberships m
              WHERE m.workspace_id = workspaces.workspace_id
                AND m.user_id = current_setting('kavrigo.user_id', true)
            )
          )
        """
    )
    # Creation scopes the transaction to the new id first, so INSERT ... RETURNING — which needs
    # SELECT visibility on the new row — succeeds without weakening the policy to `true`.
    op.execute(
        f"""
        CREATE POLICY workspaces_write ON {SCHEMA}.workspaces
          FOR ALL
          USING (workspace_id = current_setting('kavrigo.workspace_id', true))
          WITH CHECK (workspace_id = current_setting('kavrigo.workspace_id', true))
        """
    )

    # Memberships need one additional read path: resolving which workspaces a user belongs to
    # happens before any workspace is chosen, so there is no workspace to scope by yet. The
    # policy is read-only and restricted to the caller's own user id.
    op.execute(
        f"""
        CREATE POLICY memberships_self_read ON {SCHEMA}.memberships
          FOR SELECT
          USING (user_id = current_setting('kavrigo.user_id', true))
        """
    )


def _install_append_only_triggers() -> None:
    """Refuse UPDATE and DELETE on immutable tables.

    Enforced in the database because application-level immutability is a convention, and a
    convention is not what an auditor, or a future incident, needs.
    """
    op.execute(
        """
        CREATE OR REPLACE FUNCTION kavrigo.refuse_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION
            'table %.% is append-only; % is not permitted (MASTER_BUILD_SPEC.md 25, 38)',
            TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
              BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
              FOR EACH ROW EXECUTE FUNCTION kavrigo.refuse_mutation()
            """
        )


def _grant_application_privileges() -> None:
    """Grant the application role DML only.

    The role is created outside migrations (see the local bootstrap SQL and, in real
    environments, infrastructure-as-code) because role and password management is not the
    schema's business. The DO block keeps the migration runnable where the role is absent.
    """
    # SCHEMA and APP_ROLE are module constants, never request input.
    grant_sql = f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} '
                    'TO {APP_ROLE}';
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} '
                    'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}';
            -- Deliberately no DDL, no TRUNCATE, and no ownership: the application must not be
            -- able to drop a policy, disable RLS, or remove an append-only trigger.
          END IF;
        END
        $$;
        """
    op.execute(grant_sql)


def downgrade() -> None:
    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {SCHEMA}.{table}")
    op.execute("DROP FUNCTION IF EXISTS kavrigo.refuse_mutation()")
    op.execute(f"DROP POLICY IF EXISTS memberships_self_read ON {SCHEMA}.memberships")
    op.execute(f"DROP POLICY IF EXISTS workspaces_visibility ON {SCHEMA}.workspaces")
    op.execute(f"DROP POLICY IF EXISTS workspaces_write ON {SCHEMA}.workspaces")
    for table in TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_workspace_isolation ON {SCHEMA}.{table}")

    op.drop_table("audit_events", schema=SCHEMA)
    op.drop_table("idempotency_keys", schema=SCHEMA)
    op.drop_table("agent_versions", schema=SCHEMA)
    op.drop_table("agents", schema=SCHEMA)
    op.drop_table("memberships", schema=SCHEMA)
    op.drop_table("workspaces", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
