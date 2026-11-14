"""Rows a new account needs in other domains.

Auth owns *when* an account is created, not *what* the other domains store for
it; this adapter is the single seam between the two. Language-dependent settings
are deliberately absent: ``user_learning_settings`` needs a chosen language pair,
which belongs to onboarding, not to sign-in.

The model imports are local on purpose: importing another module's models at
import time would make the auth package depend on that module's router and
create an import cycle.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession


class SqlAccountDefaults:
    """Create the default settings rows for a brand-new user."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_for(self, user_id: uuid.UUID, *, now: datetime) -> None:
        # Imported here, not at module import: see the module docstring.
        from lurnian.modules.profile.models import UserSettings
        from lurnian.modules.review.models import FsrsSettings

        self._session.add(
            UserSettings(user_id=user_id, locale="fa-IR", timezone="Asia/Tehran")
        )
        self._session.add(FsrsSettings(user_id=user_id))
