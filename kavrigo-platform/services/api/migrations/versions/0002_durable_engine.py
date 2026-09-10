"""Durable engine accounts, commands, run stages and transactional outbox (ADR 0027).

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None
SCHEMA = "kavrigo"
TABLES = ("engine_accounts", "engine_commands", "engine_runs", "engine_steps", "engine_outbox")


def workspace() -> sa.Column[object]:
    return sa.Column(
        "workspace_id",
        sa.String(36),
        sa.ForeignKey("kavrigo.workspaces.workspace_id"),
        primary_key=True,
    )


def stamp(name: str, *, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "engine_accounts",
        workspace(),
        sa.Column("account_id", sa.String(128), primary_key=True),
        sa.Column("definition", sa.Text, nullable=False),
        sa.Column("definition_hash", sa.String(71), nullable=False),
        sa.Column("head_sequence", sa.Integer, nullable=False),
        sa.Column("head_hash", sa.String(71), nullable=False),
        sa.Column("head_receipt", sa.Text, nullable=False),
        sa.Column("bytes_used", sa.Integer, nullable=False),
        sa.Column("lease_token", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(128)),
        stamp("lease_until", nullable=True),
        sa.CheckConstraint(
            "head_sequence >= 0 AND head_sequence <= 1000", name="engine_account_sequence"
        ),
        sa.CheckConstraint(
            "bytes_used >= 0 AND bytes_used <= 10000000", name="engine_account_size"
        ),
        sa.CheckConstraint("lease_token >= 0", name="engine_account_fence"),
        schema=SCHEMA,
    )
    op.create_table(
        "engine_commands",
        workspace(),
        sa.Column("account_id", sa.String(128), primary_key=True),
        sa.Column("sequence", sa.Integer, primary_key=True),
        sa.Column("command_key", sa.String(128), nullable=False),
        sa.Column("command", sa.Text, nullable=False),
        sa.Column("request_hash", sa.String(71), nullable=False),
        sa.Column("receipt", sa.Text, nullable=False),
        sa.Column("state_hash", sa.String(71), nullable=False),
        stamp("occurred_at"),
        sa.Column("lease_token", sa.BigInteger, nullable=False),
        sa.Column("market_instrument", sa.String(128)),
        sa.Column("market_sequence", sa.BigInteger),
        sa.Column("market_hash", sa.String(71)),
        sa.ForeignKeyConstraint(
            ["workspace_id", "account_id"],
            ["kavrigo.engine_accounts.workspace_id", "kavrigo.engine_accounts.account_id"],
        ),
        sa.UniqueConstraint(
            "workspace_id", "account_id", "command_key", name="uq_engine_command_key"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "account_id",
            "market_instrument",
            "market_sequence",
            name="uq_engine_market_key",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "engine_runs",
        workspace(),
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("definition", sa.Text, nullable=False),
        sa.Column("input_hash", sa.String(71), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        stamp("created_at"),
        sa.Column("final_receipt", sa.Text),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','refused','uncertain')",
            name="engine_run_status",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "engine_steps",
        workspace(),
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("stage", sa.String(128), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_id", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(71), nullable=False),
        sa.Column("output", sa.Text),
        sa.Column("output_hash", sa.String(71)),
        stamp("started_at"),
        stamp("finished_at", nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["kavrigo.engine_runs.workspace_id", "kavrigo.engine_runs.run_id"],
        ),
        sa.CheckConstraint(
            "status IN ('started','completed','refused','uncertain')", name="engine_step_status"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "engine_outbox",
        workspace(),
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("topic", sa.String(32), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        stamp("created_at"),
        stamp("delivered_at", nullable=True),
        schema=SCHEMA,
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {SCHEMA}.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY {table}_workspace_isolation ON {SCHEMA}.{table}
            USING (workspace_id = current_setting('kavrigo.workspace_id', true))
            WITH CHECK (workspace_id = current_setting('kavrigo.workspace_id', true))""")
    op.execute("""CREATE TRIGGER engine_commands_append_only BEFORE UPDATE OR DELETE
        ON kavrigo.engine_commands FOR EACH ROW EXECUTE FUNCTION kavrigo.refuse_mutation()""")
    op.execute("""CREATE FUNCTION kavrigo.protect_engine_record() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'engine records cannot be deleted'; END IF;
          IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id THEN
            RAISE EXCEPTION 'engine scope is immutable';
          END IF;
          IF TG_TABLE_NAME = 'engine_accounts' AND
             ((to_jsonb(NEW)->'account_id') IS DISTINCT FROM (to_jsonb(OLD)->'account_id') OR (to_jsonb(NEW)->'definition') IS DISTINCT FROM (to_jsonb(OLD)->'definition')
              OR (to_jsonb(NEW)->'definition_hash') IS DISTINCT FROM (to_jsonb(OLD)->'definition_hash') OR (to_jsonb(NEW)->'lease_token') < (to_jsonb(OLD)->'lease_token')) THEN
            RAISE EXCEPTION 'account identity and definition are immutable';
          ELSIF TG_TABLE_NAME = 'engine_runs' AND
             ((to_jsonb(NEW)->'run_id') IS DISTINCT FROM (to_jsonb(OLD)->'run_id') OR (to_jsonb(NEW)->'definition') IS DISTINCT FROM (to_jsonb(OLD)->'definition')
              OR (to_jsonb(NEW)->'input_hash') IS DISTINCT FROM (to_jsonb(OLD)->'input_hash')
              OR (to_jsonb(OLD)->>'status') IN ('completed','refused','uncertain')) THEN
            RAISE EXCEPTION 'run identity, input and final result are immutable';
          ELSIF TG_TABLE_NAME = 'engine_steps' AND
             ((to_jsonb(NEW)->'run_id') IS DISTINCT FROM (to_jsonb(OLD)->'run_id') OR (to_jsonb(NEW)->'stage') IS DISTINCT FROM (to_jsonb(OLD)->'stage')
              OR (to_jsonb(NEW)->'input_hash') IS DISTINCT FROM (to_jsonb(OLD)->'input_hash') OR (to_jsonb(NEW)->'attempt_id') IS DISTINCT FROM (to_jsonb(OLD)->'attempt_id')
              OR (to_jsonb(OLD)->>'status') <> 'started') THEN
            RAISE EXCEPTION 'stage identity and terminal result are immutable';
          ELSIF TG_TABLE_NAME = 'engine_outbox' AND
             ((to_jsonb(NEW)->'event_id') IS DISTINCT FROM (to_jsonb(OLD)->'event_id') OR (to_jsonb(NEW)->'topic') IS DISTINCT FROM (to_jsonb(OLD)->'topic')
              OR (to_jsonb(NEW)->'payload') IS DISTINCT FROM (to_jsonb(OLD)->'payload') OR (to_jsonb(OLD)->>'delivered_at') IS NOT NULL) THEN
            RAISE EXCEPTION 'outbox event is immutable';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
    for table in ("engine_accounts", "engine_runs", "engine_steps", "engine_outbox"):
        op.execute(f"""CREATE TRIGGER {table}_protect BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
            FOR EACH ROW EXECUTE FUNCTION kavrigo.protect_engine_record()""")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kavrigo_app') THEN
            GRANT SELECT, INSERT, UPDATE ON kavrigo.engine_accounts, kavrigo.engine_runs,
                kavrigo.engine_steps, kavrigo.engine_outbox TO kavrigo_app;
            GRANT SELECT, INSERT ON kavrigo.engine_commands TO kavrigo_app;
            REVOKE DELETE ON kavrigo.engine_accounts, kavrigo.engine_commands, kavrigo.engine_runs,
                kavrigo.engine_steps, kavrigo.engine_outbox FROM kavrigo_app;
            REVOKE UPDATE ON kavrigo.engine_commands FROM kavrigo_app;
        END IF;
    END $$""")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table, schema=SCHEMA)
    op.execute("DROP FUNCTION kavrigo.protect_engine_record()")
