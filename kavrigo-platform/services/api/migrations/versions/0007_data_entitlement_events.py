"""Operator-controlled data entitlement events and activation evidence.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_EMPTY_REFS_HASH = "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"


def upgrade() -> None:
    op.create_table(
        "data_entitlement_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("license_ref", sa.String(128), nullable=False),
        sa.Column("rights", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.Column("data_packs", postgresql.ARRAY(sa.String(32)), nullable=False),
        sa.Column("contract_hash", sa.String(71)),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("event_hash", sa.String(71), nullable=False),
        sa.Column("recorded_by", sa.String(128), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(r"event_id ~ '^dee_[0-9a-f]{32}$'", name="entitlement_event_id_format"),
        sa.CheckConstraint("scope IN ('platform','workspace')", name="entitlement_scope"),
        sa.CheckConstraint("action IN ('grant','revoke')", name="entitlement_action"),
        sa.CheckConstraint(
            r"provider ~ '^[a-z0-9][a-z0-9._-]{0,63}$'", name="entitlement_provider_format"
        ),
        sa.CheckConstraint("length(license_ref) > 0", name="entitlement_license_ref_present"),
        sa.CheckConstraint(
            r"event_hash ~ '^sha256:[0-9a-f]{64}$'", name="entitlement_event_hash_format"
        ),
        sa.CheckConstraint(
            r"contract_hash IS NULL OR contract_hash ~ '^sha256:[0-9a-f]{64}$'",
            name="entitlement_contract_hash_format",
        ),
        sa.CheckConstraint(
            "(scope = 'platform' AND workspace_id IS NULL) OR "
            "(scope = 'workspace' AND workspace_id IS NOT NULL)",
            name="entitlement_workspace_scope",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_at", name="entitlement_expiry_order"
        ),
        sa.CheckConstraint(
            "rights <@ ARRAY['application_display','derived_data','agent_decision',"
            "'historical_storage']::varchar[]",
            name="entitlement_rights_closed_set",
        ),
        sa.CheckConstraint(
            "data_packs <@ ARRAY['market_microstructure','price_technical','derivatives',"
            "'onchain_core','stablecoins','etf_flows','tokenomics','defi','news','macro',"
            "'security_events','social_attention','relative_strength']::varchar[]",
            name="entitlement_data_packs_closed_set",
        ),
        sa.CheckConstraint(
            "(action = 'grant' AND cardinality(data_packs) > 0 AND "
            "((scope = 'platform' AND cardinality(rights) > 0 AND contract_hash IS NOT NULL) "
            "OR (scope = 'workspace' AND cardinality(rights) = 0 AND contract_hash IS NULL))) "
            "OR (action = 'revoke' AND cardinality(rights) = 0 "
            "AND cardinality(data_packs) = 0 AND contract_hash IS NULL)",
            name="entitlement_event_shape",
        ),
        sa.UniqueConstraint(
            "scope",
            "workspace_id",
            "provider",
            "license_ref",
            "effective_at",
            name="uq_entitlement_effective_event",
            postgresql_nulls_not_distinct=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["kavrigo.workspaces.workspace_id"], name="fk_entitlement_workspace"
        ),
        schema="kavrigo",
    )
    op.create_index(
        "ix_data_entitlement_events_lookup",
        "data_entitlement_events",
        ["provider", "license_ref", "workspace_id", "effective_at"],
        schema="kavrigo",
    )
    op.execute("ALTER TABLE kavrigo.data_entitlement_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kavrigo.data_entitlement_events FORCE ROW LEVEL SECURITY")
    op.execute("""CREATE POLICY data_entitlement_events_read
        ON kavrigo.data_entitlement_events FOR SELECT
        USING (workspace_id IS NULL OR
               workspace_id = current_setting('kavrigo.workspace_id', true))""")
    op.execute("""CREATE POLICY data_entitlement_events_operator_insert
        ON kavrigo.data_entitlement_events FOR INSERT TO kavrigo WITH CHECK (true)""")
    op.execute("""CREATE TRIGGER data_entitlement_events_append_only BEFORE UPDATE OR DELETE
        ON kavrigo.data_entitlement_events FOR EACH ROW
        EXECUTE FUNCTION kavrigo.refuse_mutation()""")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kavrigo_app') THEN
            GRANT SELECT ON kavrigo.data_entitlement_events TO kavrigo_app;
            REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
                ON kavrigo.data_entitlement_events FROM kavrigo_app;
        END IF;
    END $$""")

    op.add_column(
        "paper_activation_assessments",
        sa.Column(
            "entitlement_event_refs",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema="kavrigo",
    )
    op.add_column(
        "paper_activation_assessments",
        sa.Column(
            "entitlement_event_refs_hash",
            sa.String(71),
            nullable=False,
            server_default=_EMPTY_REFS_HASH,
        ),
        schema="kavrigo",
    )
    op.create_check_constraint(
        "activation_assessment_entitlement_refs_hash_format",
        "paper_activation_assessments",
        r"entitlement_event_refs_hash ~ '^sha256:[0-9a-f]{64}$'",
        schema="kavrigo",
    )
    op.alter_column(
        "paper_activation_assessments",
        "entitlement_event_refs",
        server_default=None,
        schema="kavrigo",
    )
    op.alter_column(
        "paper_activation_assessments",
        "entitlement_event_refs_hash",
        server_default=None,
        schema="kavrigo",
    )


def downgrade() -> None:
    op.drop_constraint(
        "activation_assessment_entitlement_refs_hash_format",
        "paper_activation_assessments",
        schema="kavrigo",
        type_="check",
    )
    op.drop_column("paper_activation_assessments", "entitlement_event_refs_hash", schema="kavrigo")
    op.drop_column("paper_activation_assessments", "entitlement_event_refs", schema="kavrigo")
    op.drop_table("data_entitlement_events", schema="kavrigo")
