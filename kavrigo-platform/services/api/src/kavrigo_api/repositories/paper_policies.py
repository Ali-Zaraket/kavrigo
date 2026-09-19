"""Immutable paper-policy candidate access, always scoped to one workspace."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kavrigo_api.db.models import PaperPolicyBundle


class PaperPolicyRepository:
    def __init__(self, session: AsyncSession, workspace_id: str) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def get(self, bundle_id: str) -> PaperPolicyBundle | None:
        return (
            await self._session.execute(
                select(PaperPolicyBundle).where(
                    PaperPolicyBundle.bundle_id == bundle_id,
                    PaperPolicyBundle.workspace_id == self._workspace_id,
                )
            )
        ).scalar_one_or_none()

    async def list(self, *, limit: int, after: str | None = None) -> list[PaperPolicyBundle]:
        stmt = select(PaperPolicyBundle).where(PaperPolicyBundle.workspace_id == self._workspace_id)
        if after is not None:
            stmt = stmt.where(PaperPolicyBundle.bundle_id > after)
        return list(
            (await self._session.execute(stmt.order_by(PaperPolicyBundle.bundle_id).limit(limit)))
            .scalars()
            .all()
        )

    async def insert(self, row: PaperPolicyBundle) -> None:
        self._session.add(row)
        await self._session.flush()
