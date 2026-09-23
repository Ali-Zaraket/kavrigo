"""Read-only access to operator-controlled data entitlement events."""

from sqlalchemy import or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from kavrigo_api.db.models import DataEntitlementEvent


class ProviderEntitlementRepository:
    def __init__(self, session: AsyncSession, workspace_id: str) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def relevant_events(
        self, provider_licenses: set[tuple[str, str]]
    ) -> list[DataEntitlementEvent]:
        if not provider_licenses:
            return []
        statement = (
            select(DataEntitlementEvent)
            .where(
                or_(
                    DataEntitlementEvent.workspace_id.is_(None),
                    DataEntitlementEvent.workspace_id == self._workspace_id,
                ),
                tuple_(DataEntitlementEvent.provider, DataEntitlementEvent.license_ref).in_(
                    provider_licenses
                ),
            )
            .order_by(DataEntitlementEvent.effective_at, DataEntitlementEvent.event_id)
        )
        return list((await self._session.execute(statement)).scalars().all())
