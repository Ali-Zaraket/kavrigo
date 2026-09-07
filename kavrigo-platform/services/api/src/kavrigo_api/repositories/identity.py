"""User, workspace and membership access."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from kavrigo_api.auth.principal import Role
from kavrigo_api.db.models import Membership, User, Workspace
from kavrigo_api.db.session import set_workspace_scope

__all__ = [
    "IdentityRepository",
    "MembershipRow",
    "new_user_id",
    "new_workspace_id",
]

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")

LAST_SEEN_REFRESH = timedelta(minutes=15)
"""How stale ``last_seen_at`` may get before a request refreshes it."""


def new_user_id() -> str:
    return f"usr_{uuid.uuid4().hex}"


def new_workspace_id() -> str:
    return f"ws_{uuid.uuid4().hex}"


class MembershipRow:
    """A workspace plus the calling user's role in it."""

    __slots__ = ("created_at", "name", "role", "slug", "workspace_id")

    def __init__(
        self, workspace_id: str, name: str, slug: str, role: Role, created_at: datetime
    ) -> None:
        self.workspace_id = workspace_id
        self.name = name
        self.slug = slug
        self.role = role
        self.created_at = created_at


class IdentityRepository:
    """Users, workspaces and memberships.

    These operate on a global session because they answer questions asked *before* a workspace
    is chosen. Membership reads are constrained to the caller's own ``user_id`` — both here and,
    independently, by the ``memberships_self_read`` policy.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_user(self, *, external_id: str, email: str | None) -> User:
        """Find or create the local user for an identity-provider subject.

        Read first, and write only when something actually changed. Every authenticated request
        passes through here, so an unconditional upsert would mean a write transaction — and a
        row-version bump, and WAL — on every request the platform serves, for no information.

        ``last_seen_at`` is refreshed at most once per :data:`LAST_SEEN_REFRESH`; it is a
        coarse activity signal, not an audit timestamp, and the audit trail records actions
        precisely (``MASTER_BUILD_SPEC.md`` §25).

        The insert path still uses ``ON CONFLICT`` because two concurrent first requests for the
        same new account would otherwise race and one would fail on the unique constraint.
        """
        now = datetime.now(UTC)
        existing = await self.get_user_by_external_id(external_id)
        if existing is not None:
            stale = existing.last_seen_at is None or now - existing.last_seen_at > LAST_SEEN_REFRESH
            if stale or existing.email != email:
                await self._session.execute(
                    update(User)
                    .where(User.user_id == existing.user_id)
                    .values(last_seen_at=now, email=email)
                )
            return existing

        stmt = (
            pg_insert(User)
            .values(
                user_id=new_user_id(),
                external_id=external_id,
                email=email,
                created_at=now,
                last_seen_at=now,
            )
            .on_conflict_do_update(
                index_elements=[User.external_id],
                set_={"last_seen_at": now, "email": email},
            )
            .returning(User)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def get_user_by_external_id(self, external_id: str) -> User | None:
        result = await self._session.execute(select(User).where(User.external_id == external_id))
        return result.scalar_one_or_none()

    async def create_workspace(self, *, name: str, slug: str, owner_user_id: str) -> Workspace:
        """Create a workspace and make the creator its owner.

        Both rows are written in one transaction: a workspace with no owner would be
        unadministrable and invisible to its creator.
        """
        if not _SLUG.match(slug):
            raise ValueError(f"invalid workspace slug: {slug!r}")

        # Scope the transaction to the identifier before writing anything. Both tables are
        # protected by row-level security whose WITH CHECK clause reads this setting, and
        # `INSERT ... RETURNING` additionally needs SELECT visibility on the new row. Generating
        # the id up front is what lets the policies stay strict through the bootstrap.
        workspace_id = new_workspace_id()
        await set_workspace_scope(self._session, workspace_id)

        workspace = Workspace(workspace_id=workspace_id, name=name, slug=slug)
        self._session.add(workspace)
        await self._session.flush()

        self._session.add(
            Membership(
                workspace_id=workspace_id,
                user_id=owner_user_id,
                role=Role.OWNER.value,
            )
        )
        await self._session.flush()
        return workspace

    async def list_memberships(self, user_id: str) -> list[MembershipRow]:
        """Workspaces the user belongs to, with their role in each."""
        result = await self._session.execute(
            select(
                Workspace.workspace_id,
                Workspace.name,
                Workspace.slug,
                Membership.role,
                Workspace.created_at,
            )
            .join(Membership, Membership.workspace_id == Workspace.workspace_id)
            .where(Membership.user_id == user_id, Workspace.archived_at.is_(None))
            .order_by(Workspace.created_at)
        )
        return [MembershipRow(row[0], row[1], row[2], Role(row[3]), row[4]) for row in result.all()]

    async def get_role(self, *, workspace_id: str, user_id: str) -> Role | None:
        """The caller's role in one workspace, or ``None`` if they are not a member.

        ``None`` is the authorization answer, not an error: the caller simply has no standing in
        this workspace, and the identity provider's organization claim does not override it.
        """
        result = await self._session.execute(
            select(Membership.role).where(
                Membership.workspace_id == workspace_id, Membership.user_id == user_id
            )
        )
        role = result.scalar_one_or_none()
        return Role(role) if role is not None else None
