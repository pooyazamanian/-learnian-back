"""Ports the auth use cases depend on.

The application layer talks to these protocols only, so it never imports
SQLAlchemy, FastAPI or a vendor SDK. That is the dependency-inversion part of
SOLID: infrastructure implements the protocol, the use case owns it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from lurnian.core.enums import ChallengePurpose, SessionRevokedReason

if TYPE_CHECKING:
    # Entities are the only concrete types crossing the boundary; importing them
    # for typing keeps this module free of ORM/session setup.
    from lurnian.modules.auth.infrastructure.identity_models import (
        User,
        VerificationChallenge,
    )
    from lurnian.modules.auth.infrastructure.security_models import (
        RefreshToken,
        UserSession,
    )


class UnitOfWork(Protocol):
    """Transaction boundary owned by the use case, not by each repository."""

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class UserRepository(Protocol):
    """Persistence of the root account record."""

    async def by_id(self, user_id: uuid.UUID) -> User | None: ...

    async def by_phone(self, phone: str) -> User | None: ...

    async def create_or_get(self, phone: str, *, now: datetime) -> tuple[User, bool]:
        """Return ``(user, created)``; safe against a concurrent first login."""
        ...

    async def touch_login(self, user: User, *, now: datetime) -> None: ...


class ChallengeRepository(Protocol):
    """Persistence of one-time codes."""

    async def latest_pending(
        self, destination: str, purpose: ChallengePurpose
    ) -> VerificationChallenge | None: ...

    async def invalidate_pending(
        self, destination: str, *, purpose: ChallengePurpose, now: datetime
    ) -> None: ...

    async def add(self, challenge: VerificationChallenge) -> None: ...

    async def get_for_update(
        self, challenge_id: uuid.UUID
    ) -> VerificationChallenge | None:
        """Lock the row so two verifications cannot both consume the code."""
        ...

    async def count_for_destination(self, destination: str, *, since: datetime) -> int:
        """How many codes this number requested since ``since``."""
        ...

    async def count_for_ip(self, ip: str, *, since: datetime) -> int:
        """How many codes this address requested since ``since``."""
        ...


class SessionRepository(Protocol):
    """Persistence of sessions and refresh tokens."""

    async def add_session(self, session: UserSession) -> None: ...

    async def add_refresh_token(self, token: RefreshToken) -> None: ...

    async def refresh_token_by_hash(
        self, token_hash: bytes, *, for_update: bool = False
    ) -> RefreshToken | None: ...

    async def consume_refresh_token(
        self, token_id: uuid.UUID, *, now: datetime
    ) -> bool:
        """Mark the token used; ``False`` means another request won the race."""
        ...

    async def session_by_id(self, session_id: uuid.UUID) -> UserSession | None: ...

    async def sessions_for_user(
        self, user_id: uuid.UUID, *, active_only: bool
    ) -> Sequence[UserSession]: ...

    async def touch_session(self, session: UserSession, *, now: datetime) -> None: ...

    async def revoke_session(
        self,
        session_id: uuid.UUID,
        *,
        now: datetime,
        reason: SessionRevokedReason,
    ) -> bool: ...

    async def revoke_session_tokens(
        self,
        session_id: uuid.UUID,
        *,
        now: datetime,
        reason: SessionRevokedReason,
    ) -> None: ...

    async def revoke_family(
        self,
        family_id: uuid.UUID,
        *,
        now: datetime,
        reason: SessionRevokedReason,
    ) -> None: ...

    async def revoke_all_sessions(
        self,
        user_id: uuid.UUID,
        *,
        now: datetime,
        reason: SessionRevokedReason,
        keep_session_id: uuid.UUID | None,
    ) -> int: ...


class AccountDefaults(Protocol):
    """Rows a brand-new account needs outside the auth tables."""

    async def create_for(self, user_id: uuid.UUID, *, now: datetime) -> None: ...


class SmsSender(Protocol):
    """Outbound OTP delivery."""

    async def send_code(self, *, phone: str, code: str) -> None: ...


class TokenIssuer(Protocol):
    """Signs stateless access tokens. Refresh tokens are opaque and stored."""

    @property
    def access_ttl_seconds(self) -> int: ...

    def issue(self, *, user_id: uuid.UUID, session_id: uuid.UUID) -> str: ...


#: Re-exported for type checkers reading the protocols above.
__all__ = [
    "AccountDefaults",
    "ChallengeRepository",
    "SessionRepository",
    "SmsSender",
    "TokenIssuer",
    "UnitOfWork",
    "UserRepository",
]
