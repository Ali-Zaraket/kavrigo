"""Control-plane schema (``MASTER_BUILD_SPEC.md`` §16.6, §20, §38).

PostgreSQL holds authoritative tenant, configuration and versioning state. Three properties are
enforced in the database rather than only in application code, because application code is one
forgotten ``WHERE`` clause away from being wrong:

* **Tenant isolation** — row-level security on every tenant-scoped table, keyed on the
  ``kavrigo.workspace_id`` session variable set by :mod:`kavrigo_api.db.session`.
* **Immutability** — triggers refuse ``UPDATE`` and ``DELETE`` on ``agent_versions`` and
  ``audit_events``. Runs reference immutable versions; rewriting one would silently rewrite the
  explanation of a historical decision.
* **Referential integrity** — an agent version cannot reference a workspace its agent does not
  belong to.

RLS is defence in depth, not the only check: every repository still scopes its queries.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

__all__ = [
    "SCHEMA",
    "Agent",
    "AgentVersionRow",
    "AuditEvent",
    "Base",
    "IdempotencyKey",
    "Membership",
    "User",
    "Workspace",
]

SCHEMA = "kavrigo"

#: Tenant-scoped tables. Migrations enable and FORCE row-level security on each of these, and a
#: test asserts this list matches what the database actually reports — a new table that forgets
#: RLS is a tenant-isolation bug, so it must fail loudly rather than be discovered later.
TENANT_SCOPED_TABLES: tuple[str, ...] = (
    "memberships",
    "agents",
    "agent_versions",
    "idempotency_keys",
    "audit_events",
)

#: The workspace registry also has row-level security, but with its own policy rather than the
#: standard workspace-isolation one: listing a user's workspaces necessarily happens before any
#: workspace has been chosen, so membership (keyed on ``kavrigo.user_id``) is a second
#: visibility path alongside the scoped workspace.
SELF_POLICIED_TABLES: tuple[str, ...] = ("workspaces",)

#: Tables that may never be updated or deleted from.
APPEND_ONLY_TABLES: tuple[str, ...] = ("agent_versions", "audit_events")

_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base with a stable naming convention.

    Named constraints matter for migrations: an auto-generated name differs between PostgreSQL
    versions and turns a routine ``DROP CONSTRAINT`` into an incident.
    """

    metadata = MetaData(schema=SCHEMA, naming_convention=_NAMING_CONVENTION)


def _ts(**kwargs: Any) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), **kwargs)


class User(Base):
    """A person. Global, not tenant-scoped: one account can belong to several workspaces.

    The platform stores its own record keyed on the identity provider's subject rather than
    using the provider id directly, so that changing provider (ADR: Clerk today, possibly
    WorkOS/Auth0 later) does not rewrite every foreign key.
    """

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime | None] = _ts()

    __table_args__ = (
        CheckConstraint(r"user_id ~ '^usr_[0-9a-f]{32}$'", name="user_id_format"),
        {"schema": SCHEMA},
    )


class Workspace(Base):
    """The tenant boundary itself."""

    __tablename__ = "workspaces"

    workspace_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    archived_at: Mapped[datetime | None] = _ts()

    memberships: Mapped[list[Membership]] = relationship(back_populates="workspace")

    __table_args__ = (
        CheckConstraint(r"workspace_id ~ '^ws_[0-9a-f]{32}$'", name="workspace_id_format"),
        CheckConstraint(r"slug ~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$'", name="slug_format"),
        {"schema": SCHEMA},
    )


class Membership(Base):
    """A user's role in a workspace. The only source of truth for tenant authorization.

    An identity provider's organization claim is a hint; this table is the decision.
    """

    __tablename__ = "memberships"

    workspace_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.workspaces.workspace_id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.users.user_id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")

    __table_args__ = (
        CheckConstraint("role IN ('owner','admin','member','viewer')", name="role_valid"),
        Index("ix_memberships_user", "user_id"),
        {"schema": SCHEMA},
    )


class Agent(Base):
    """An agent. Mutable metadata only — behaviour lives in immutable versions."""

    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey(f"{SCHEMA}.workspaces.workspace_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    archived_at: Mapped[datetime | None] = _ts()

    __table_args__ = (
        CheckConstraint(r"agent_id ~ '^ag_[0-9a-f]{32}$'", name="agent_id_format"),
        CheckConstraint(r"name ~ '^[a-z0-9][a-z0-9-]*$'", name="name_format"),
        CheckConstraint("current_version >= 0", name="current_version_non_negative"),
        UniqueConstraint("workspace_id", "name", name="uq_agents_workspace_name"),
        {"schema": SCHEMA},
    )


class AgentVersionRow(Base):
    """An immutable agent version (``MASTER_BUILD_SPEC.md`` §38).

    The stored ``spec`` is a validated :class:`kavrigo_domain.AgentSpec` serialised to JSONB, and
    ``spec_hash`` is its canonical content hash. Storing the hash alongside the document lets a
    later reader detect tampering or an encoding change rather than trusting the row.

    ``UPDATE`` and ``DELETE`` are refused by a trigger. Promotion state is therefore represented
    by inserting a new row in the promotion table rather than mutating this one.
    """

    __tablename__ = "agent_versions"

    agent_version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    spec_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    prompt_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    author_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="human")
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    approved_environments: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, default=list
    )

    __table_args__ = (
        CheckConstraint(r"agent_version_id ~ '^av_[0-9a-f]{32}$'", name="version_id_format"),
        CheckConstraint(r"spec_hash ~ '^sha256:[0-9a-f]{64}$'", name="spec_hash_format"),
        CheckConstraint(r"prompt_hash ~ '^sha256:[0-9a-f]{64}$'", name="prompt_hash_format"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "author_kind IN ('human','ai_assisted','ai_generated')", name="author_kind_valid"
        ),
        CheckConstraint(
            "approval_status IN ('pending','approved','rejected','withdrawn')",
            name="approval_status_valid",
        ),
        UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
        # The composite foreign key is what prevents a version being attached to an agent in a
        # different workspace — a single-column FK to agent_id would not.
        ForeignKeyConstraint(
            ["agent_id", "workspace_id"],
            [f"{SCHEMA}.agents.agent_id", f"{SCHEMA}.agents.workspace_id"],
            ondelete="CASCADE",
            name="fk_agent_versions_agent",
        ),
        Index("ix_agent_versions_workspace_agent", "workspace_id", "agent_id", "version"),
        {"schema": SCHEMA},
    )


class IdempotencyKey(Base):
    """Recorded results of state-changing requests (``MASTER_BUILD_SPEC.md`` §49).

    ``request_hash`` is stored so that reusing a key with a *different* body is detected and
    rejected, rather than silently returning the earlier unrelated response.
    """

    __tablename__ = "idempotency_keys"

    workspace_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = _ts(nullable=False)

    __table_args__ = (
        Index("ix_idempotency_keys_expires", "expires_at"),
        {"schema": SCHEMA},
    )


class AuditEvent(Base):
    """Append-only audit trail (``MASTER_BUILD_SPEC.md`` §25).

    ``UPDATE`` and ``DELETE`` are refused by a trigger. This is the platform's own record; it is
    not the same thing as an observability trace, and it is not stored in a vendor's system.
    """

    __tablename__ = "audit_events"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    subject_type: Mapped[str | None] = mapped_column(String(64))
    subject_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_audit_events_workspace_created", "workspace_id", "created_at"),
        Index("ix_audit_events_subject", "workspace_id", "subject_type", "subject_id"),
        {"schema": SCHEMA},
    )
