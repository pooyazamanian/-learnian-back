"""Dependency wiring: the composition root of the auth context.

Concrete adapters are chosen here and nowhere else. Every use case receives its
collaborators through the constructor, which is what makes them replaceable in
tests without a database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lurnian.core.config import Settings, get_settings
from lurnian.core.database import get_db_session
from lurnian.core.enums import UserStatus
from lurnian.core.exceptions import AuthenticationError
from lurnian.core.security import decode_access_token
from lurnian.modules.auth.application.auth_service import AuthService
from lurnian.modules.auth.application.ports import (
    AccountDefaults,
    ChallengeRepository,
    SmsSender,
    TokenIssuer,
    UnitOfWork,
    UserRepository,
)
from lurnian.modules.auth.application.session_service import SessionService
from lurnian.modules.auth.infrastructure.account_defaults import SqlAccountDefaults
from lurnian.modules.auth.infrastructure.identity_models import User
from lurnian.modules.auth.infrastructure.repositories import (
    SqlChallengeRepository,
    SqlSessionRepository,
    SqlUnitOfWork,
    SqlUserRepository,
)
from lurnian.modules.auth.infrastructure.security_models import UserSession
from lurnian.modules.auth.infrastructure.sms import LoggingSmsSender
from lurnian.modules.auth.infrastructure.tokens import JwtTokenIssuer

AsyncSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_bearer = HTTPBearer(
    auto_error=False,
    description="Access token returned by POST /api/v1/auth/otp/verify",
)


@dataclass(frozen=True, slots=True)
class CurrentPrincipal:
    """The verified caller behind a request."""

    user_id: uuid.UUID
    session_id: uuid.UUID


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: AsyncSessionDep,
    settings: SettingsDep,
) -> CurrentPrincipal:
    """Resolve the caller from a signed token *and* its live session.

    The token is stateless, but revocation is not: closing the session row takes
    effect on the next request instead of at token expiry.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Authentication required")

    claims = decode_access_token(
        credentials.credentials,
        secret=settings.jwt_secret.get_secret_value(),
        issuer=settings.jwt_issuer,
    )
    statement = (
        select(UserSession.id, UserSession.user_id)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.id == claims.session_id,
            UserSession.revoked_at.is_(None),
            UserSession.absolute_expires_at > func.now(),
            User.deleted_at.is_(None),
            User.status == UserStatus.ACTIVE,
        )
    )
    row = (await session.execute(statement)).first()
    if row is None:
        raise AuthenticationError("Session is no longer active")
    if row.user_id != claims.subject:
        raise AuthenticationError("Token does not match its session")
    return CurrentPrincipal(user_id=row.user_id, session_id=row.id)


#: Short alias for protected endpoints.
Principal = Annotated[CurrentPrincipal, Depends(get_current_principal)]


def get_unit_of_work(session: AsyncSessionDep) -> UnitOfWork:
    return SqlUnitOfWork(session)


def get_user_repository(session: AsyncSessionDep) -> UserRepository:
    return SqlUserRepository(session)


def get_challenge_repository(session: AsyncSessionDep) -> ChallengeRepository:
    return SqlChallengeRepository(session)


def get_account_defaults(session: AsyncSessionDep) -> AccountDefaults:
    return SqlAccountDefaults(session)


def get_sms_sender(settings: SettingsDep) -> SmsSender:
    """Log the code locally; a real provider replaces this one class."""
    return LoggingSmsSender(include_code=settings.environment == "development")


def get_token_issuer(settings: SettingsDep) -> TokenIssuer:
    return JwtTokenIssuer(settings)


def get_session_service(
    session: AsyncSessionDep,
    token_issuer: Annotated[TokenIssuer, Depends(get_token_issuer)],
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    settings: SettingsDep,
) -> SessionService:
    """Build the session use case over one request-scoped session."""
    return SessionService(
        sessions=SqlSessionRepository(session),
        tokens=token_issuer,
        uow=uow,
        settings=settings,
    )


def get_auth_service(
    users: Annotated[UserRepository, Depends(get_user_repository)],
    challenges: Annotated[ChallengeRepository, Depends(get_challenge_repository)],
    sessions: Annotated[SessionService, Depends(get_session_service)],
    defaults: Annotated[AccountDefaults, Depends(get_account_defaults)],
    sms: Annotated[SmsSender, Depends(get_sms_sender)],
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    settings: SettingsDep,
) -> AuthService:
    """Build the sign-in use case with its ports."""
    return AuthService(
        users=users,
        challenges=challenges,
        sessions=sessions,
        defaults=defaults,
        sms=sms,
        uow=uow,
        settings=settings,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]
