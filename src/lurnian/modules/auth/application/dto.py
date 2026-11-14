"""Data carried between the use cases and the HTTP layer.

These are plain records, not Pydantic models: the application layer must not
depend on the web framework.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from lurnian.modules.auth.infrastructure.identity_models import User


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    """A freshly issued access/refresh pair bound to one session."""

    access_token: str
    refresh_token: str
    session_id: uuid.UUID
    expires_in: int
    refresh_expires_in: int


@dataclass(frozen=True, slots=True)
class IssuedChallenge:
    """The outcome of asking for a sign-in code."""

    challenge_id: uuid.UUID
    expires_in: int
    resend_after: int
    debug_code: str | None = None


@dataclass(frozen=True, slots=True)
class LoginResult:
    """An authenticated (possibly brand-new) user plus its first token pair."""

    user: User
    is_new_user: bool
    tokens: IssuedTokens


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """One session as shown on the "where am I signed in" screen."""

    id: uuid.UUID
    current: bool
    auth_method: str
    ip: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime | None
