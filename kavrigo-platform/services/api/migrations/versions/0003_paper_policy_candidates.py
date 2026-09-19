"""Immutable, tenant-scoped paper policy candidates; no approval or activation.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_policy_bundles",
        sa.Column("bundle_id", sa.String(35), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("kavrigo.workspaces.workspace_id"),
            nullable=False,
        ),
        sa.Column("risk_policy_id", sa.String(35), nullable=False, unique=True),
        sa.Column("execution_policy_id", sa.String(35), nullable=False, unique=True),
        sa.Column("risk_document", postgresql.JSONB, nullable=False),
        sa.Column("risk_hash", sa.String(71), nullable=False),
        sa.Column("execution_document", postgresql.JSONB, nullable=False),
        sa.Column("execution_hash", sa.String(71), nullable=False),
        sa.Column("request_hash", sa.String(71), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(r"bundle_id ~ '^pb_[0-9a-f]{32}$'", name="bundle_id_format"),
        sa.CheckConstraint(r"risk_policy_id ~ '^rp_[0-9a-f]{32}$'", name="risk_id_format"),
        sa.CheckConstraint(
            r"execution_policy_id ~ '^ep_[0-9a-f]{32}$'", name="execution_id_format"
        ),
        sa.CheckConstraint(r"risk_hash ~ '^sha256:[0-9a-f]{64}$'", name="risk_hash_format"),
        sa.CheckConstraint(
            r"execution_hash ~ '^sha256:[0-9a-f]{64}$'", name="execution_hash_format"
        ),
        sa.CheckConstraint(r"request_hash ~ '^sha256:[0-9a-f]{64}$'", name="request_hash_format"),
        schema="kavrigo",
    )
    op.create_index(
        "ix_paper_policy_bundles_workspace_id",
        "paper_policy_bundles",
        ["workspace_id", "bundle_id"],
        schema="kavrigo",
    )
    op.execute("ALTER TABLE kavrigo.paper_policy_bundles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kavrigo.paper_policy_bundles FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY paper_policy_bundles_workspace_isolation
        ON kavrigo.paper_policy_bundles
        USING (workspace_id = current_setting('kavrigo.workspace_id', true))
        WITH CHECK (workspace_id = current_setting('kavrigo.workspace_id', true))""")
    op.execute("""CREATE TRIGGER paper_policy_bundles_append_only BEFORE UPDATE OR DELETE
        ON kavrigo.paper_policy_bundles FOR EACH ROW
        EXECUTE FUNCTION kavrigo.refuse_mutation()""")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kavrigo_app') THEN
            GRANT SELECT, INSERT ON kavrigo.paper_policy_bundles TO kavrigo_app;
            REVOKE UPDATE, DELETE ON kavrigo.paper_policy_bundles FROM kavrigo_app;
        END IF;
    END $$""")


def downgrade() -> None:
    op.drop_table("paper_policy_bundles", schema="kavrigo")
