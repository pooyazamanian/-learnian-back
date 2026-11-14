"""Auth endpoints: code request, verification, refresh, sessions.

The router is a thin translator: validate input, call one use case, map its
result to a schema. No query, no business rule and no token logic lives here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response, status

from lurnian.core.enums import SessionRevokedReason
from lurnian.core.exceptions import AuthenticationError
from lurnian.modules.auth.application.dto import IssuedTokens, SessionInfo
from lurnian.modules.auth.infrastructure.identity_models import User
from lurnian.modules.auth.presentation.dependencies import (
    AuthServiceDep,
    Principal,
    SessionServiceDep,
    UserRepositoryDep,
)
from lurnian.modules.auth.presentation.schemas import (
    AuthResponse,
    OtpRequestedResponse,
    OtpVerifyRequest,
    PhoneRequest,
    RefreshRequest,
    RevokeAllRequest,
    RevokeAllResponse,
    SessionListResponse,
    SessionResponse,
    TokenPair,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

#: One shared default instance: building a model per call in a signature is a
#: footgun ruff flags (B008), and this body carries no mutable state.
_DEFAULT_REVOKE_ALL = RevokeAllRequest()


@router.post(
    "/otp/request",
    response_model=OtpRequestedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a sign-in code",
    description=(
        "Create a one-time SMS code for a phone number. A brand-new number is "
        "accepted here and gets its account on verification, so the response is "
        "identical for new and returning users."
    ),
)
async def request_code(
    payload: PhoneRequest,
    request: Request,
    service: AuthServiceDep,
) -> OtpRequestedResponse:
    """Create and send a code without revealing whether the phone is known."""
    issued = await service.request_code(
        phone=payload.phone, request_ip=_client_ip(request)
    )
    return OtpRequestedResponse(
        challenge_id=issued.challenge_id,
        expires_in=issued.expires_in,
        resend_after=issued.resend_after,
        debug_code=issued.debug_code,
    )


@router.post(
    "/otp/verify",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify a code and sign in",
    description=(
        "Consume the code, create the account if this is the first sign-in, and "
        "return the user together with an access/refresh pair."
    ),
)
async def verify_code(
    payload: OtpVerifyRequest,
    request: Request,
    service: AuthServiceDep,
) -> AuthResponse:
    """Open a session and hand back the user in one round trip."""
    result = await service.verify_code(
        challenge_id=payload.challenge_id,
        code=payload.code,
        request_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return AuthResponse(
        user=_user_response(result.user),
        tokens=_token_pair(result.tokens),
        is_new_user=result.is_new_user,
    )


@router.post(
    "/refresh",
    response_model=TokenPair,
    status_code=status.HTTP_200_OK,
    summary="Rotate tokens",
    description=(
        "Consume a refresh token and return a new pair. Reusing an already "
        "consumed token revokes its whole family and closes the session."
    ),
)
async def refresh(
    payload: RefreshRequest,
    service: SessionServiceDep,
) -> TokenPair:
    """Rotate the caller's refresh token."""
    return _token_pair(await service.rotate(refresh_token=payload.refresh_token))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out of this device",
    description="Revoke the current session and every refresh token it owns.",
)
async def logout(principal: Principal, service: SessionServiceDep) -> Response:
    """Close the session named by the presented access token."""
    await service.revoke(
        user_id=principal.user_id,
        session_id=principal.session_id,
        reason=SessionRevokedReason.LOGOUT,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Current account",
    description="Return the account behind the presented access token.",
)
async def me(principal: Principal, users: UserRepositoryDep) -> UserResponse:
    """Return the signed-in user's own record."""
    user = await users.by_id(principal.user_id)
    if user is None:
        raise AuthenticationError(
            "Account is no longer available", code="auth.account_missing"
        )
    return _user_response(user)


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List live sessions",
    description="Show every device that can still refresh this account.",
)
async def list_sessions(
    principal: Principal, service: SessionServiceDep
) -> SessionListResponse:
    """Return the user's active sessions, marking the caller's own."""
    sessions = await service.list_sessions(
        user_id=principal.user_id, current_session_id=principal.session_id
    )
    return SessionListResponse(sessions=[_session_response(row) for row in sessions])


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Close one session",
    description="Revoke any session of the caller by its id.",
)
async def revoke_session(
    session_id: uuid.UUID,
    principal: Principal,
    service: SessionServiceDep,
) -> Response:
    """Close one session the caller owns."""
    await service.revoke(
        user_id=principal.user_id,
        session_id=session_id,
        reason=SessionRevokedReason.LOGOUT,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/revoke-all",
    response_model=RevokeAllResponse,
    status_code=status.HTTP_200_OK,
    summary="Close every other session",
    description=(
        "Revoke all sessions of the caller, optionally keeping the one that made "
        "this request."
    ),
)
async def revoke_all_sessions(
    principal: Principal,
    service: SessionServiceDep,
    payload: RevokeAllRequest = _DEFAULT_REVOKE_ALL,
) -> RevokeAllResponse:
    """Close every other device without signing this one out."""
    revoked = await service.revoke_all(
        user_id=principal.user_id,
        reason=SessionRevokedReason.LOGOUT_ALL,
        keep_session_id=principal.session_id if payload.keep_current else None,
    )
    return RevokeAllResponse(revoked_count=revoked)


def _client_ip(request: Request) -> str | None:
    """Return the peer address, if the server exposed one."""
    return request.client.host if request.client else None


def _token_pair(tokens: IssuedTokens) -> TokenPair:
    """Map the domain token bundle to the API schema."""
    return TokenPair(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
        refresh_expires_in=tokens.refresh_expires_in,
        session_id=tokens.session_id,
    )


def _user_response(user: User) -> UserResponse:
    """Build the public user view without credentials or internal flags."""
    return UserResponse(
        id=user.id,
        phone=user.phone_e164,
        phone_verified_at=user.phone_verified_at,
        status=user.status.value,
        created_at=user.created_at,
    )


def _session_response(session: SessionInfo) -> SessionResponse:
    """Map one domain session to the API schema."""
    return SessionResponse(
        id=session.id,
        current=session.current,
        auth_method=session.auth_method,
        ip=session.ip,
        user_agent=session.user_agent,
        created_at=session.created_at,
        last_seen_at=session.last_seen_at,
        expires_at=session.expires_at,
    )
