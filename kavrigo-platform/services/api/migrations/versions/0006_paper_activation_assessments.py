"""Immutable, fail-closed paper-activation assessments.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_agent_version_activation_scope",
        "agent_versions",
        ["agent_version_id", "agent_id", "version", "workspace_id"],
        schema="kavrigo",
    )
    op.create_unique_constraint(
        "uq_paper_approval_workspace",
        "paper_policy_approvals",
        ["approval_id", "workspace_id"],
        schema="kavrigo",
    )
    op.create_table(
        "paper_activation_assessments",
        sa.Column("assessment_id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("agent_version_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("bundle_id", sa.String(35), nullable=False),
        sa.Column("approval_id", sa.String(35), nullable=False),
        sa.Column("evaluation_run_id", sa.String(36), nullable=False),
        sa.Column("agent_spec_hash", sa.String(71), nullable=False),
        sa.Column("risk_hash", sa.String(71), nullable=False),
        sa.Column("execution_hash", sa.String(71), nullable=False),
        sa.Column("evaluation_input_hash", sa.String(71), nullable=False),
        sa.Column("evaluation_output_hash", sa.String(71)),
        sa.Column("providers", postgresql.ARRAY(sa.String(64)), nullable=False),
        sa.Column("license_refs", postgresql.ARRAY(sa.String(128)), nullable=False),
        sa.Column("gate_results", postgresql.JSONB, nullable=False),
        sa.Column("gate_hash", sa.String(71), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(71), nullable=False),
        sa.Column("assessed_by", sa.String(36), nullable=False),
        sa.Column(
            "assessed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            r"assessment_id ~ '^paa_[0-9a-f]{32}$'", name="activation_assessment_id_format"
        ),
        sa.CheckConstraint(
            "decision IN ('blocked','eligible')", name="activation_assessment_decision"
        ),
        sa.CheckConstraint("version >= 1", name="activation_assessment_version_positive"),
        sa.CheckConstraint(
            r"agent_spec_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="activation_assessment_spec_hash_format",
        ),
        sa.CheckConstraint(
            r"risk_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="activation_assessment_risk_hash_format",
        ),
        sa.CheckConstraint(
            r"execution_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="activation_assessment_execution_hash_format",
        ),
        sa.CheckConstraint(
            r"evaluation_input_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="activation_assessment_input_hash_format",
        ),
        sa.CheckConstraint(
            r"evaluation_output_hash IS NULL OR evaluation_output_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="activation_assessment_output_hash_format",
        ),
        sa.CheckConstraint(
            r"gate_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="activation_assessment_gate_hash_format",
        ),
        sa.CheckConstraint(
            r"request_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="activation_assessment_request_hash_format",
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id", "agent_id", "version", "workspace_id"],
            [
                "kavrigo.agent_versions.agent_version_id",
                "kavrigo.agent_versions.agent_id",
                "kavrigo.agent_versions.version",
                "kavrigo.agent_versions.workspace_id",
            ],
            name="fk_activation_assessment_agent_version",
        ),
        sa.ForeignKeyConstraint(
            ["bundle_id", "workspace_id"],
            ["kavrigo.paper_policy_bundles.bundle_id", "kavrigo.paper_policy_bundles.workspace_id"],
            name="fk_activation_assessment_bundle",
        ),
        sa.ForeignKeyConstraint(
            ["approval_id", "workspace_id"],
            [
                "kavrigo.paper_policy_approvals.approval_id",
                "kavrigo.paper_policy_approvals.workspace_id",
            ],
            name="fk_activation_assessment_approval",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "evaluation_run_id"],
            ["kavrigo.engine_runs.workspace_id", "kavrigo.engine_runs.run_id"],
            name="fk_activation_assessment_run",
        ),
        schema="kavrigo",
    )
    op.create_index(
        "ix_paper_activation_assessments_workspace_version",
        "paper_activation_assessments",
        ["workspace_id", "agent_version_id", "assessment_id"],
        schema="kavrigo",
    )
    op.execute("ALTER TABLE kavrigo.paper_activation_assessments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kavrigo.paper_activation_assessments FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY paper_activation_assessments_workspace_isolation
        ON kavrigo.paper_activation_assessments
        USING (workspace_id = current_setting('kavrigo.workspace_id', true))
        WITH CHECK (workspace_id = current_setting('kavrigo.workspace_id', true))""")
    op.execute("""CREATE TRIGGER paper_activation_assessments_append_only BEFORE UPDATE OR DELETE
        ON kavrigo.paper_activation_assessments FOR EACH ROW
        EXECUTE FUNCTION kavrigo.refuse_mutation()""")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kavrigo_app') THEN
            GRANT SELECT, INSERT ON kavrigo.paper_activation_assessments TO kavrigo_app;
            REVOKE UPDATE, DELETE ON kavrigo.paper_activation_assessments FROM kavrigo_app;
        END IF;
    END $$""")


def downgrade() -> None:
    op.drop_table("paper_activation_assessments", schema="kavrigo")
    op.drop_constraint(
        "uq_paper_approval_workspace",
        "paper_policy_approvals",
        schema="kavrigo",
        type_="unique",
    )
    op.drop_constraint(
        "uq_agent_version_activation_scope",
        "agent_versions",
        schema="kavrigo",
        type_="unique",
    )
