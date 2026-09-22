"""Append-only approvals for exact, independently reviewed paper policies.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_paper_review_workspace",
        "paper_policy_reviews",
        ["review_id", "workspace_id"],
        schema="kavrigo",
    )
    op.create_table(
        "paper_policy_approvals",
        sa.Column("approval_id", sa.String(35), primary_key=True),
        sa.Column("review_id", sa.String(35), nullable=False, unique=True),
        sa.Column("bundle_id", sa.String(35), nullable=False, unique=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("risk_hash", sa.String(71), nullable=False),
        sa.Column("execution_hash", sa.String(71), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(71), nullable=False),
        sa.Column("approved_by", sa.String(36), nullable=False),
        sa.Column(
            "approved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(r"approval_id ~ '^pa_[0-9a-f]{32}$'", name="approval_id_format"),
        sa.CheckConstraint(
            r"risk_hash ~ '^sha256:[0-9a-f]{64}$'", name="approval_risk_hash_format"
        ),
        sa.CheckConstraint(
            r"execution_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="approval_execution_hash_format",
        ),
        sa.CheckConstraint(
            r"request_hash ~ '^sha256:[0-9a-f]{64}$'", name="approval_request_hash_format"
        ),
        sa.ForeignKeyConstraint(
            ["review_id", "workspace_id"],
            ["kavrigo.paper_policy_reviews.review_id", "kavrigo.paper_policy_reviews.workspace_id"],
            name="fk_paper_approval_review_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["bundle_id", "workspace_id"],
            ["kavrigo.paper_policy_bundles.bundle_id", "kavrigo.paper_policy_bundles.workspace_id"],
            name="fk_paper_approval_bundle_workspace",
        ),
        schema="kavrigo",
    )
    op.create_index(
        "ix_paper_policy_approvals_workspace_id",
        "paper_policy_approvals",
        ["workspace_id", "bundle_id"],
        schema="kavrigo",
    )
    op.execute("ALTER TABLE kavrigo.paper_policy_approvals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kavrigo.paper_policy_approvals FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY paper_policy_approvals_workspace_isolation
        ON kavrigo.paper_policy_approvals
        USING (workspace_id = current_setting('kavrigo.workspace_id', true))
        WITH CHECK (workspace_id = current_setting('kavrigo.workspace_id', true))""")
    op.execute("""CREATE TRIGGER paper_policy_approvals_append_only BEFORE UPDATE OR DELETE
        ON kavrigo.paper_policy_approvals FOR EACH ROW
        EXECUTE FUNCTION kavrigo.refuse_mutation()""")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kavrigo_app') THEN
            GRANT SELECT, INSERT ON kavrigo.paper_policy_approvals TO kavrigo_app;
            REVOKE UPDATE, DELETE ON kavrigo.paper_policy_approvals FROM kavrigo_app;
        END IF;
    END $$""")


def downgrade() -> None:
    op.drop_table("paper_policy_approvals", schema="kavrigo")
    op.drop_constraint(
        "uq_paper_review_workspace", "paper_policy_reviews", schema="kavrigo", type_="unique"
    )
