"""Request and response bodies for the auth API.

Names follow the endpoints, not the tables: ``/otp/request`` returns a challenge
id, ``/otp/verify`` returns the user together with the token pair.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PhoneRequest(BaseModel):
    """Ask for a sign-in code."""

    phone: str = Field(
        min_length=7,
        max_length=32,
        examples=["09121234567", "+989121234567"],
        description="Any common format; stored as E.164.",
    )


class OtpRequestedResponse(BaseModel):
    """A challenge was created and (in development) its code is echoed."""

    challenge_id: uuid.UUID
    expires_in: int = Field(description="Seconds the code stays valid")
    resend_after: int = Field(description="Seconds before another code is allowed")
    debug_code: str | None = Field(
        default=None, description="Development only; null in real environments"
    )


class OtpVerifyRequest(BaseModel):
    """Exchange a code for a session."""

    challenge_id: uuid.UUID
    code: str = Field(pattern=r"^\d{4,8}$", examples=["123456"])


class RefreshRequest(BaseModel):
    """Rotate a refresh token into a new pair."""

    refresh_token: str = Field(min_length=20, max_length=200)


class TokenPair(BaseModel):
    """The only time the raw refresh token is ever returned."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")
    refresh_expires_in: int = Field(description="Refresh token lifetime in seconds")
    session_id: uuid.UUID


class UserResponse(BaseModel):
    """Public view of the signed-in account."""

    id: uuid.UUID
    phone: str | None
    phone_verified_at: datetime | None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    """Account plus a fresh token pair, returned right after sign-in."""

    user: UserResponse
    tokens: TokenPair
    is_new_user: bool


class SessionResponse(BaseModel):
    """One live session of the caller."""

    id: uuid.UUID
    current: bool
    auth_method: str
    ip: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime | None


class SessionListResponse(BaseModel):
    """All live sessions, newest first."""

    sessions: list[SessionResponse]


class RevokeAllRequest(BaseModel):
    """Revoke every other session; keep this one unless told otherwise."""

    keep_current: bool = True


class RevokeAllResponse(BaseModel):
    """How many sessions were closed."""

    revoked_count: int
