"""Append-only paper-activation assessment access, scoped to one workspace."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kavrigo_api.db.models import PaperActivationAssessment


class PaperActivationRepository:
    def __init__(self, session: AsyncSession, workspace_id: str) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def get(self, assessment_id: str) -> PaperActivationAssessment | None:
        return (
            await self._session.execute(
                select(PaperActivationAssessment).where(
                    PaperActivationAssessment.assessment_id == assessment_id,
                    PaperActivationAssessment.workspace_id == self._workspace_id,
                )
            )
        ).scalar_one_or_none()

    async def insert(self, row: PaperActivationAssessment) -> None:
        self._session.add(row)
        await self._session.flush()
