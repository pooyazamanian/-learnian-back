"""Read-only profile queries used by other domains."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lurnian.modules.profile.models import UserSettings

#: Fallback when a user has no settings row yet; matches the column default.
DEFAULT_TIMEZONE = "Asia/Tehran"


class ProfileQuery:
    """Read side of the Profile domain."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def timezone(self, user_id: uuid.UUID) -> str:
        """Return the IANA timezone that defines the user's calendar day."""
        timezone = await self._session.scalar(
            select(UserSettings.timezone).where(UserSettings.user_id == user_id)
        )
        return timezone or DEFAULT_TIMEZONE
