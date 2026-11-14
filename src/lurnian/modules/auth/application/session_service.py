"""Session lifecycle: issue, rotate, list and revoke.

Sessions and refresh tokens are the unit of "sign me out", so this is the only
place that writes them. The service never touches HTTP and never builds SQL: it
depends on repositories and a token issuer (see ``ports``).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from lurnian.core.config import Settings
from lurnian.core.enums import AuthMethod, SessionRevokedReason
from lurnian.core.exceptions import AuthenticationError, NotFoundError
from lurnian.core.security import generate_opaque_token, hash_opaque_token
from lurnian.core.types import new_uuid
from lurnian.modules.auth.application.dto import IssuedTokens, SessionInfo
from lurnian.modules.auth.application.ports import (
    SessionRepository,
    TokenIssuer,
    UnitOfWork,
)
from lurnian.modules.auth.domain.clock import is_expired, utcnow
from lurnian.modules.auth.infrastructure.security_models import (
    RefreshToken,
    UserSession,
)


class SessionService:
    """Single responsibility: the life of a session and its refresh chain."""

    def __init__(
        self,
        *,
        sessions: SessionRepository,
        tokens: TokenIssuer,
        uow: UnitOfWork,
        settings: Settings,
    ) -> None:
        self._sessions = sessions
        self._tokens = tokens
        self._uow = uow
        self._settings = settings

    async def start(
        self,
        *,
        user_id: uuid.UUID,
        method: AuthMethod,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> IssuedTokens:
        """Open a session and return its first token pair."""
        now = utcnow()
        session_id = new_uuid()
        await self._sessions.add_session(
            UserSession(
                id=session_id,
                user_id=user_id,
                auth_method=method,
                ip=ip,
                user_agent=user_agent,
                created_at=now,
                last_seen_at=now,
                absolute_expires_at=now
                + timedelta(days=self._settings.session_absolute_ttl_days),
            )
        )
        refresh_token = await self._issue_refresh_token(
            session_id=session_id, family_id=None, parent_id=None, now=now
        )
        return self._tokens_for(
            user_id=user_id, session_id=session_id, refresh_token=refresh_token
        )

    async def rotate(self, *, refresh_token: str) -> IssuedTokens:
        """Consume a refresh token and return its successor.

        Reuse of an already-consumed token revokes the whole family *and* the
        session before raising, so a stolen token is useless after one rotation.
        """
        now = utcnow()
        row = await self._sessions.refresh_token_by_hash(
            hash_opaque_token(refresh_token), for_update=True
        )
        if row is None:
            raise AuthenticationError(
                "Invalid refresh token", code="auth.refresh_invalid"
            )

        if row.used_at is not None:
            await self._revoke_chain(row, now=now)
            raise AuthenticationError(
                "Refresh token already used; sign in again",
                code="auth.refresh_reused",
            )

        if row.revoked_at is not None or is_expired(row.expires_at, now=now):
            raise AuthenticationError(
                "Refresh token expired; sign in again", code="auth.refresh_expired"
            )

        if not await self._sessions.consume_refresh_token(row.id, now=now):
            # Another request consumed it between the read and the update.
            await self._revoke_chain(row, now=now)
            raise AuthenticationError(
                "Refresh token already used; sign in again",
                code="auth.refresh_reused",
            )

        session = await self._sessions.session_by_id(row.session_id)
        if (
            session is None
            or session.revoked_at is not None
            or is_expired(session.absolute_expires_at, now=now)
        ):
            raise AuthenticationError(
                "Session is no longer active", code="auth.session_revoked"
            )

        await self._sessions.touch_session(session, now=now)
        successor = await self._issue_refresh_token(
            session_id=row.session_id,
            family_id=row.family_id,
            parent_id=row.id,
            now=now,
        )
        await self._uow.commit()
        return self._tokens_for(
            user_id=session.user_id,
            session_id=row.session_id,
            refresh_token=successor,
        )

    async def list_sessions(
        self, *, user_id: uuid.UUID, current_session_id: uuid.UUID
    ) -> Sequence[SessionInfo]:
        """Return the user's live sessions, marking the caller's own."""
        rows = await self._sessions.sessions_for_user(user_id, active_only=True)
        return [
            SessionInfo(
                id=row.id,
                current=row.id == current_session_id,
                auth_method=row.auth_method.value,
                ip=row.ip,
                user_agent=row.user_agent,
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
                expires_at=row.absolute_expires_at,
            )
            for row in rows
        ]

    async def revoke(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        reason: SessionRevokedReason,
    ) -> uuid.UUID:
        """Revoke one session of this user together with its refresh tokens."""
        session = await self._sessions.session_by_id(session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError("Session not found")

        now = utcnow()
        await self._sessions.revoke_session(session_id, now=now, reason=reason)
        await self._sessions.revoke_session_tokens(session_id, now=now, reason=reason)
        await self._uow.commit()
        return session_id

    async def revoke_all(
        self,
        *,
        user_id: uuid.UUID,
        reason: SessionRevokedReason,
        keep_session_id: uuid.UUID | None = None,
    ) -> int:
        """Revoke every other session of this user ("log out everywhere")."""
        revoked = await self._sessions.revoke_all_sessions(
            user_id, now=utcnow(), reason=reason, keep_session_id=keep_session_id
        )
        await self._uow.commit()
        return revoked

    async def _revoke_chain(self, token: RefreshToken, *, now: datetime) -> None:
        """Kill the token family, its session and commit before raising."""
        reason = SessionRevokedReason.REUSE_DETECTED
        await self._sessions.revoke_family(token.family_id, now=now, reason=reason)
        await self._sessions.revoke_session(token.session_id, now=now, reason=reason)
        await self._sessions.revoke_session_tokens(
            token.session_id, now=now, reason=reason
        )
        await self._uow.commit()

    async def _issue_refresh_token(
        self,
        *,
        session_id: uuid.UUID,
        family_id: uuid.UUID | None,
        parent_id: uuid.UUID | None,
        now: datetime,
    ) -> str:
        """Store the hash of a new refresh token and return the raw value once."""
        token_id = new_uuid()
        raw_token = generate_opaque_token()
        await self._sessions.add_refresh_token(
            RefreshToken(
                id=token_id,
                session_id=session_id,
                token_hash=hash_opaque_token(raw_token),
                family_id=family_id or token_id,
                parent_id=parent_id,
                issued_at=now,
                expires_at=now + timedelta(days=self._settings.refresh_token_ttl_days),
            )
        )
        return raw_token

    def _tokens_for(
        self, *, user_id: uuid.UUID, session_id: uuid.UUID, refresh_token: str
    ) -> IssuedTokens:
        """Bundle a signed access token with the freshly created refresh token."""
        return IssuedTokens(
            access_token=self._tokens.issue(user_id=user_id, session_id=session_id),
            refresh_token=refresh_token,
            session_id=session_id,
            expires_in=self._tokens.access_ttl_seconds,
            refresh_expires_in=self._settings.refresh_token_ttl_days * 86_400,
        )
