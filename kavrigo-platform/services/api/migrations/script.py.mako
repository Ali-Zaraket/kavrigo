"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Created: ${create_date}

Security and tenancy checklist for every migration touching a tenant-scoped table:
  * ENABLE and FORCE ROW LEVEL SECURITY;
  * add the workspace isolation policy;
  * grant only the privileges the application role needs;
  * add the table to TENANT_SCOPED_TABLES in db/models.py so the RLS test covers it.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | None = ${repr(branch_labels)}
depends_on: str | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
