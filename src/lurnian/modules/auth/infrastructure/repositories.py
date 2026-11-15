"""SQLAlchemy implementations of the auth ports.

Repositories contain queries only: no business decisions and no commits. The
use case decides *when* the transaction ends, which keeps a failed login from
leaving half-written rows behind.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lurnian.core.enums import ChallengePurpose, SessionRevokedReason, UserStatus
from lurnian.core.exceptions import ConflictError
from lurnian.core.types import new_uuid
from lurnian.modules.auth.infrastructure.identity_models import (
    User,
    VerificationChallenge,
)
from lurnian.modules.auth.infrastructure.security_models import (
    RefreshToken,
    UserSession,
)


class SqlUnitOfWork:
    """The request-scoped session, exposed only as commit/rollback."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class SqlUserRepository:
    """Reads and writes the ``users`` row that owns an identity."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.scalar(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )

    async def by_phone(self, phone: str) -> User | None:
        return await self._session.scalar(
            select(User).where(User.phone_e164 == phone, User.deleted_at.is_(None))
        )

    async def create_or_get(self, phone: str, *, now: datetime) -> tuple[User, bool]:
        """Insert on first sign-in, otherwise return the existing account.

        A savepoint makes a lost race harmless: the unique index rejects the
        duplicate, the savepoint rolls back, and the winner's row is returned.
        """
        user = User(
            id=new_uuid(),
            phone_e164=phone,
            phone_verified_at=now,
            status=UserStatus.ACTIVE,
            last_active_at=now,
            # Set in Python so the object is complete before the row is
            # re-read; server defaults only arrive on a later SELECT.
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(user)
                await self._session.flush()
        except IntegrityError:
            existing = await self.by_phone(phone) or await self._session.scalar(
                select(User).where(User.phone_e164 == phone)
            )
            if existing is None:
                raise ConflictError(
                    "This phone number is not available",
                    code="auth.phone_unavailable",
                ) from None
            return existing, False
        return user, True

    async def touch_login(self, user: User, *, now: datetime) -> None:
        user.last_active_at = now
        if user.phone_verified_at is None:
            user.phone_verified_at = now
        await self._session.flush()


class SqlChallengeRepository:
    """Reads and writes one-time codes; never stores the code itself."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_pending(
        self, destination: str, purpose: ChallengePurpose
    ) -> VerificationChallenge | None:
        return await self._session.scalar(
            select(VerificationChallenge)
            .where(
                VerificationChallenge.destination == destination,
                VerificationChallenge.purpose == purpose,
                VerificationChallenge.consumed_at.is_(None),
                VerificationChallenge.invalidated_at.is_(None),
            )
            .order_by(VerificationChallenge.created_at.desc())
            .limit(1)
        )

    async def invalidate_pending(
        self, destination: str, *, purpose: ChallengePurpose, now: datetime
    ) -> None:
        await self._session.execute(
            update(VerificationChallenge)
            .where(
                VerificationChallenge.destination == destination,
                VerificationChallenge.purpose == purpose,
                VerificationChallenge.consumed_at.is_(None),
                VerificationChallenge.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
        )

    async def add(self, challenge: VerificationChallenge) -> None:
        if challenge.id is None:
            challenge.id = new_uuid()
        self._session.add(challenge)
        await self._session.flush()

    async def get_for_update(
        self, challenge_id: uuid.UUID
    ) -> VerificationChallenge | None:
        return await self._session.scalar(
            select(VerificationChallenge)
            .where(VerificationChallenge.id == challenge_id)
            .with_for_update()
        )

    async def count_for_destination(self, destination: str, *, since: datetime) -> int:
        return await self._count(
            VerificationChallenge.destination == destination, since=since
        )

    async def count_for_ip(self, ip: str, *, since: datetime) -> int:
        return await self._count(VerificationChallenge.request_ip == ip, since=since)

    async def _count(self, criterion: ColumnElement[bool], *, since: datetime) -> int:
        """Count challenges matching ``criterion`` created since ``since``."""
        statement = (
            select(func.count())
            .select_from(VerificationChallenge)
            .where(
                criterion,
                VerificationChallenge.created_at >= since,
            )
        )
        return int(await self._session.scalar(statement) or 0)


class SqlSessionRepository:
    """Reads and writes ``user_sessions`` and ``refresh_tokens``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_session(self, session: UserSession) -> None:
        self._session.add(session)        # Flush now: the refresh token references this row and there is no ORM
        # relationship telling SQLAlchemy to order the two INSERTs. Without the
        # flush the token can be written first and hit the FK violation.
        await self._session.flush()

    async def add_refresh_token(self, token: RefreshToken) -> None:
        self._session.add(token)
        await self._session.flush()

    async def refresh_token_by_hash(
        self, token_hash: bytes, *, for_update: bool = False
    ) -> RefreshToken | None:
        statement = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def consume_refresh_token(
        self, token_id: uuid.UUID, *, now: datetime
    ) -> bool:
        result = await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id, RefreshToken.used_at.is_(None))
            .values(used_at=now)
        )
        return result.rowcount == 1

    async def session_by_id(self, session_id: uuid.UUID) -> UserSession | None:
        return await self._session.get(UserSession, session_id)

    async def sessions_for_user(
        self, user_id: uuid.UUID, *, active_only: bool
    ) -> Sequence[UserSession]:
        statement = select(UserSession).where(UserSession.user_id == user_id)
        if active_only:
            statement = statement.where(UserSession.revoked_at.is_(None))
        statement = statement.order_by(UserSession.created_at.desc())
        return list(await self._session.scalars(statement))

    async def touch_session(self, session: UserSession, *, now: datetime) -> None:
        session.last_seen_at = now
        await self._session.flush()

    async def revoke_session(
        self,
        session_id: uuid.UUID,
        *,
        now: datetime,
        reason: SessionRevokedReason,
    ) -> bool:
        result = await self._session.execute(
            update(UserSession)
            .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
        )
        return result.rowcount == 1

    async def revoke_session_tokens(
        self,
        session_id: uuid.UUID,
        *,
        now: datetime,
        reason: SessionRevokedReason,
    ) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.session_id == session_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason=reason)
        )

    async def revoke_family(
        self,
        family_id: uuid.UUID,
        *,
        now: datetime,
        reason: SessionRevokedReason,
    ) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason=reason)
        )

    async def revoke_all_sessions(
        self,
        user_id: uuid.UUID,
        *,
        now: datetime,
        reason: SessionRevokedReason,
        keep_session_id: uuid.UUID | None,
    ) -> int:
        statement = select(UserSession.id).where(
            UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
        )
        if keep_session_id is not None:
            statement = statement.where(UserSession.id != keep_session_id)
        session_ids = list(await self._session.scalars(statement))
        if not session_ids:
            return 0

        await self._session.execute(
            update(UserSession)
            .where(UserSession.id.in_(session_ids))
            .values(revoked_at=now, revoked_reason=reason)
        )
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.session_id.in_(session_ids),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason=reason)
        )
        return len(session_ids)
