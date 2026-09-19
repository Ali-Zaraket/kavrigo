"""Append-only, tenant-scoped paper policy review recommendations.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_paper_bundle_workspace",
        "paper_policy_bundles",
        ["bundle_id", "workspace_id"],
        schema="kavrigo",
    )
    op.create_table(
        "paper_policy_reviews",
        sa.Column("review_id", sa.String(35), primary_key=True),
        sa.Column("bundle_id", sa.String(35), nullable=False, unique=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("recommendation", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("risk_hash", sa.String(71), nullable=False),
        sa.Column("execution_hash", sa.String(71), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(71), nullable=False),
        sa.Column("reviewed_by", sa.String(36), nullable=False),
        sa.Column(
            "reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(r"review_id ~ '^pr_[0-9a-f]{32}$'", name="review_id_format"),
        sa.CheckConstraint(
            "recommendation IN ('advance_to_evaluation', 'changes_requested')",
            name="review_recommendation",
        ),
        sa.CheckConstraint(r"risk_hash ~ '^sha256:[0-9a-f]{64}$'", name="review_risk_hash_format"),
        sa.CheckConstraint(
            r"execution_hash ~ '^sha256:[0-9a-f]{64}$'", name="review_execution_hash_format"
        ),
        sa.CheckConstraint(
            r"request_hash ~ '^sha256:[0-9a-f]{64}$'", name="review_request_hash_format"
        ),
        sa.ForeignKeyConstraint(
            ["bundle_id", "workspace_id"],
            ["kavrigo.paper_policy_bundles.bundle_id", "kavrigo.paper_policy_bundles.workspace_id"],
            name="fk_paper_review_bundle_workspace",
        ),
        schema="kavrigo",
    )
    op.create_index(
        "ix_paper_policy_reviews_workspace_id",
        "paper_policy_reviews",
        ["workspace_id", "bundle_id"],
        schema="kavrigo",
    )
    op.execute("ALTER TABLE kavrigo.paper_policy_reviews ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kavrigo.paper_policy_reviews FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY paper_policy_reviews_workspace_isolation
        ON kavrigo.paper_policy_reviews
        USING (workspace_id = current_setting('kavrigo.workspace_id', true))
        WITH CHECK (workspace_id = current_setting('kavrigo.workspace_id', true))""")
    op.execute("""CREATE TRIGGER paper_policy_reviews_append_only BEFORE UPDATE OR DELETE
        ON kavrigo.paper_policy_reviews FOR EACH ROW
        EXECUTE FUNCTION kavrigo.refuse_mutation()""")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kavrigo_app') THEN
            GRANT SELECT, INSERT ON kavrigo.paper_policy_reviews TO kavrigo_app;
            REVOKE UPDATE, DELETE ON kavrigo.paper_policy_reviews FROM kavrigo_app;
        END IF;
    END $$""")


def downgrade() -> None:
    op.drop_table("paper_policy_reviews", schema="kavrigo")
    op.drop_constraint(
        "uq_paper_bundle_workspace", "paper_policy_bundles", schema="kavrigo", type_="unique"
    )
