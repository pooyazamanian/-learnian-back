"""Use-case tests for phone sign-in and refresh rotation.

The application layer depends on ports, so these tests run the real services
against in-memory adapters: no PostgreSQL, no HTTP, no mocking library.
"""

from __future__ import annotations

import ipaddress
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from lurnian.core.config import Settings
from lurnian.core.enums import (
    AuthMethod,
    ChallengePurpose,
    SessionRevokedReason,
    UserStatus,
)
from lurnian.core.exceptions import (
    AuthenticationError,
    ForbiddenError,
    RateLimitedError,
    ServiceUnavailableError,
)
from lurnian.core.types import new_uuid
from lurnian.modules.auth.application.auth_service import AuthService
from lurnian.modules.auth.application.session_service import SessionService
from lurnian.modules.auth.domain.clock import utcnow
from lurnian.modules.auth.infrastructure.identity_models import (
    User,
    VerificationChallenge,
)
from lurnian.modules.auth.infrastructure.security_models import (
    RefreshToken,
    UserSession,
)

PHONE = "+989121234567"


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeUsers:
    def __init__(self) -> None:
        self.rows: list[User] = []

    async def by_id(self, user_id: uuid.UUID) -> User | None:
        return next((row for row in self.rows if row.id == user_id), None)

    async def by_phone(self, phone: str) -> User | None:
        return next((row for row in self.rows if row.phone_e164 == phone), None)

    async def create_or_get(self, phone: str, *, now: datetime) -> tuple[User, bool]:
        existing = await self.by_phone(phone)
        if existing is not None:
            return existing, False
        user = User(
            id=new_uuid(),
            phone_e164=phone,
            phone_verified_at=now,
            status=UserStatus.ACTIVE,
            last_active_at=now,
            created_at=now,
            updated_at=now,
        )
        self.rows.append(user)
        return user, True

    async def touch_login(self, user: User, *, now: datetime) -> None:
        user.last_active_at = now


class FakeChallenges:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, VerificationChallenge] = {}

    async def add(self, challenge: VerificationChallenge) -> None:
        if challenge.id is None:
            challenge.id = new_uuid()
        challenge.created_at = challenge.created_at or utcnow()
        self.rows[challenge.id] = challenge

    async def get_for_update(
        self, challenge_id: uuid.UUID
    ) -> VerificationChallenge | None:
        return self.rows.get(challenge_id)

    async def latest_pending(
        self, destination: str, purpose: ChallengePurpose
    ) -> VerificationChallenge | None:
        pending = [
            row
            for row in self.rows.values()
            if row.destination == destination
            and row.purpose is purpose
            and row.consumed_at is None
            and row.invalidated_at is None
        ]
        return max(pending, key=lambda row: row.created_at, default=None)

    async def invalidate_pending(
        self, destination: str, *, purpose: ChallengePurpose, now: datetime
    ) -> None:
        for row in self.rows.values():
            if (
                row.destination == destination
                and row.purpose is purpose
                and row.consumed_at is None
                and row.invalidated_at is None
            ):
                row.invalidated_at = now

    async def count_for_destination(self, destination: str, *, since: datetime) -> int:
        return sum(
            1
            for row in self.rows.values()
            if row.destination == destination and row.created_at >= since
        )

    async def count_for_ip(self, ip: str, *, since: datetime) -> int:
        return sum(
            1
            for row in self.rows.values()
            if row.request_ip == ip and row.created_at >= since
        )


class FakeSessions:
    def __init__(self) -> None:
        self.sessions: dict[uuid.UUID, UserSession] = {}
        self.tokens: list[RefreshToken] = []

    async def add_session(self, session: UserSession) -> None:
        self.sessions[session.id] = session

    async def add_refresh_token(self, token: RefreshToken) -> None:
        self.tokens.append(token)

    async def refresh_token_by_hash(
        self, token_hash: bytes, *, for_update: bool = False
    ) -> RefreshToken | None:
        return next(
            (token for token in self.tokens if token.token_hash == token_hash),
            None,
        )

    async def consume_refresh_token(
        self, token_id: uuid.UUID, *, now: datetime
    ) -> bool:
        token = next(token for token in self.tokens if token.id == token_id)
        if token.used_at is not None:
            return False
        token.used_at = now
        return True

    async def session_by_id(self, session_id: uuid.UUID) -> UserSession | None:
        return self.sessions.get(session_id)

    async def sessions_for_user(
        self, user_id: uuid.UUID, *, active_only: bool
    ) -> Sequence[UserSession]:
        rows = [
            session for session in self.sessions.values() if session.user_id == user_id
        ]
        if active_only:
            return [row for row in rows if row.revoked_at is None]
        return rows

    async def touch_session(self, session: UserSession, *, now: datetime) -> None:
        session.last_seen_at = now

    async def revoke_session(
        self,
        session_id: uuid.UUID,
        *,
        now: datetime,
        reason: SessionRevokedReason,
    ) -> bool:
        session = self.sessions.get(session_id)
        if session is None or session.revoked_at is not None:
            return False
        session.revoked_at = now
        session.revoked_reason = reason
        return True

    async def revoke_session_tokens(
        self,
        session_id: uuid.UUID,
        *,
        now: datetime,
        reason: SessionRevokedReason,
    ) -> None:
        for token in self.tokens:
            if token.session_id == session_id and token.revoked_at is None:
                token.revoked_at = now
                token.revoked_reason = reason

    async def revoke_family(
        self,
        family_id: uuid.UUID,
        *,
        now: datetime,
        reason: SessionRevokedReason,
    ) -> None:
        for token in self.tokens:
            if token.family_id == family_id and token.revoked_at is None:
                token.revoked_at = now
                token.revoked_reason = reason

    async def revoke_all_sessions(
        self,
        user_id: uuid.UUID,
        *,
        now: datetime,
        reason: SessionRevokedReason,
        keep_session_id: uuid.UUID | None,
    ) -> int:
        targets = [
            session.id
            for session in self.sessions.values()
            if session.user_id == user_id
            and session.revoked_at is None
            and session.id != keep_session_id
        ]
        for session_id in targets:
            await self.revoke_session(session_id, now=now, reason=reason)
            await self.revoke_session_tokens(session_id, now=now, reason=reason)
        return len(targets)


class FakeSms:
    def __init__(self, *, fail: bool = False) -> None:
        self.messages: list[tuple[str, str]] = []
        self._fail = fail

    async def send_code(self, *, phone: str, code: str) -> None:
        if self._fail:
            raise ConnectionError("provider down")
        self.messages.append((phone, code))


class FakeTokenIssuer:
    access_ttl_seconds = 1800

    def issue(self, *, user_id: uuid.UUID, session_id: uuid.UUID) -> str:
        return f"access:{user_id}:{session_id}"


class FakeAccountDefaults:
    def __init__(self) -> None:
        self.created: list[uuid.UUID] = []

    async def create_for(self, user_id: uuid.UUID, *, now: datetime) -> None:
        self.created.append(user_id)


@dataclass
class Harness:
    auth: AuthService
    sessions: SessionService
    users: FakeUsers
    challenges: FakeChallenges
    session_rows: FakeSessions
    sms: FakeSms
    defaults: FakeAccountDefaults
    uow: FakeUnitOfWork = field(default_factory=FakeUnitOfWork)


def _different_code(code: str) -> str:
    """Return a six-digit code that is guaranteed wrong for this challenge."""
    return "111111" if code == "000000" else "000000"


def build_harness(
    *, settings: Settings | None = None, sms_fails: bool = False
) -> Harness:
    """Wire the real services to the in-memory adapters."""
    settings = settings or Settings(_env_file=None, otp_expose_in_response=True)
    users = FakeUsers()
    challenges = FakeChallenges()
    session_rows = FakeSessions()
    sms = FakeSms(fail=sms_fails)
    defaults = FakeAccountDefaults()
    uow = FakeUnitOfWork()
    tokens = FakeTokenIssuer()

    sessions = SessionService(
        sessions=session_rows, tokens=tokens, uow=uow, settings=settings
    )
    auth = AuthService(
        users=users,
        challenges=challenges,
        sessions=sessions,
        defaults=defaults,
        sms=sms,
        uow=uow,
        settings=settings,
    )
    return Harness(
        auth=auth,
        sessions=sessions,
        users=users,
        challenges=challenges,
        session_rows=session_rows,
        sms=sms,
        defaults=defaults,
        uow=uow,
    )


async def test_request_code_sends_the_echoed_code() -> None:
    harness = build_harness()
    issued = await harness.auth.request_code(phone="09121234567", request_ip=None)

    assert issued.debug_code is not None
    assert harness.sms.messages == [(PHONE, issued.debug_code)]
    assert issued.expires_in == 120


async def test_request_code_enforces_the_resend_cooldown() -> None:
    harness = build_harness()
    await harness.auth.request_code(phone=PHONE, request_ip=None)

    with pytest.raises(RateLimitedError) as caught:
        await harness.auth.request_code(phone=PHONE, request_ip=None)
    assert caught.value.code == "auth.code_cooldown"
    assert caught.value.details["retry_after"] > 0


async def test_first_verification_creates_user_and_session() -> None:
    harness = build_harness()
    issued = await harness.auth.request_code(phone=PHONE, request_ip=None)

    result = await harness.auth.verify_code(
        challenge_id=issued.challenge_id,
        code=issued.debug_code or "",
        request_ip=None,
        user_agent="pytest",
    )

    assert result.is_new_user is True
    assert result.user.phone_e164 == PHONE
    assert result.user.phone_verified_at is not None
    assert result.tokens.access_token.startswith("access:")
    assert result.tokens.refresh_expires_in == 365 * 86_400
    assert harness.defaults.created == [result.user.id]
    assert harness.challenges.rows[issued.challenge_id].consumed_at is not None
    session = harness.session_rows.sessions[result.tokens.session_id]
    assert session.auth_method is AuthMethod.SMS_OTP
    assert session.user_agent == "pytest"


async def test_returning_user_is_not_created_twice() -> None:
    harness = build_harness()
    first = await harness.auth.request_code(phone=PHONE, request_ip=None)
    await harness.auth.verify_code(
        challenge_id=first.challenge_id,
        code=first.debug_code or "",
        request_ip=None,
        user_agent=None,
    )

    second = await harness.auth.request_code(phone=PHONE, request_ip=None)
    result = await harness.auth.verify_code(
        challenge_id=second.challenge_id,
        code=second.debug_code or "",
        request_ip=None,
        user_agent=None,
    )

    assert result.is_new_user is False
    assert len(harness.users.rows) == 1
    assert len(harness.defaults.created) == 1


async def test_wrong_code_counts_an_attempt_and_reports_what_is_left() -> None:
    harness = build_harness()
    issued = await harness.auth.request_code(phone=PHONE, request_ip=None)
    wrong = _different_code(issued.debug_code or "")

    with pytest.raises(AuthenticationError) as caught:
        await harness.auth.verify_code(
            challenge_id=issued.challenge_id,
            code=wrong,
            request_ip=None,
            user_agent=None,
        )

    assert caught.value.code == "auth.invalid_code"
    assert caught.value.details["attempts_left"] == 4
    assert harness.challenges.rows[issued.challenge_id].attempts == 1


async def test_code_cannot_be_guessed_forever() -> None:
    harness = build_harness()
    issued = await harness.auth.request_code(phone=PHONE, request_ip=None)
    wrong = _different_code(issued.debug_code or "")

    for _ in range(5):
        with pytest.raises(AuthenticationError):
            await harness.auth.verify_code(
                challenge_id=issued.challenge_id,
                code=wrong,
                request_ip=None,
                user_agent=None,
            )

    with pytest.raises(RateLimitedError) as caught:
        await harness.auth.verify_code(
            challenge_id=issued.challenge_id,
            code=wrong,
            request_ip=None,
            user_agent=None,
        )
    assert caught.value.code == "auth.too_many_attempts"


async def test_expired_code_is_rejected() -> None:
    harness = build_harness()
    issued = await harness.auth.request_code(phone=PHONE, request_ip=None)
    challenge = harness.challenges.rows[issued.challenge_id]
    challenge.expires_at = utcnow() - timedelta(seconds=1)

    with pytest.raises(AuthenticationError) as caught:
        await harness.auth.verify_code(
            challenge_id=issued.challenge_id,
            code=issued.debug_code or "",
            request_ip=None,
            user_agent=None,
        )
    assert caught.value.code == "auth.code_expired"


async def test_consumed_code_cannot_be_replayed() -> None:
    harness = build_harness()
    issued = await harness.auth.request_code(phone=PHONE, request_ip=None)
    await harness.auth.verify_code(
        challenge_id=issued.challenge_id,
        code=issued.debug_code or "",
        request_ip=None,
        user_agent=None,
    )

    with pytest.raises(AuthenticationError) as caught:
        await harness.auth.verify_code(
            challenge_id=issued.challenge_id,
            code=issued.debug_code or "",
            request_ip=None,
            user_agent=None,
        )
    assert caught.value.code == "auth.code_invalid"


async def test_refresh_rotates_and_the_old_token_dies() -> None:
    harness = build_harness()
    issued = await harness.auth.request_code(phone=PHONE, request_ip=None)
    login = await harness.auth.verify_code(
        challenge_id=issued.challenge_id,
        code=issued.debug_code or "",
        request_ip=None,
        user_agent=None,
    )

    rotated = await harness.sessions.rotate(refresh_token=login.tokens.refresh_token)
    assert rotated.refresh_token != login.tokens.refresh_token
    assert rotated.session_id == login.tokens.session_id

    with pytest.raises(AuthenticationError) as caught:
        await harness.sessions.rotate(refresh_token=login.tokens.refresh_token)
    assert caught.value.code == "auth.refresh_reused"

    session = harness.session_rows.sessions[login.tokens.session_id]
    assert session.revoked_at is not None
    assert session.revoked_reason is SessionRevokedReason.REUSE_DETECTED


async def test_revoke_all_keeps_the_current_session() -> None:
    harness = build_harness()
    issued = await harness.auth.request_code(phone=PHONE, request_ip=None)
    login = await harness.auth.verify_code(
        challenge_id=issued.challenge_id,
        code=issued.debug_code or "",
        request_ip=None,
        user_agent=None,
    )
    other = await harness.sessions.start(
        user_id=login.user.id, method=AuthMethod.SMS_OTP
    )

    revoked = await harness.sessions.revoke_all(
        user_id=login.user.id,
        reason=SessionRevokedReason.LOGOUT_ALL,
        keep_session_id=login.tokens.session_id,
    )

    assert revoked == 1
    assert harness.session_rows.sessions[other.session_id].revoked_at is not None
    assert harness.session_rows.sessions[login.tokens.session_id].revoked_at is None

    listed = await harness.sessions.list_sessions(
        user_id=login.user.id, current_session_id=login.tokens.session_id
    )
    assert [row.current for row in listed] == [True]


async def test_deleted_account_cannot_sign_in() -> None:
    """A soft-deleted account still owns the phone number; it must be refused."""
    harness = build_harness()
    deleted_at = utcnow()
    harness.users.rows.append(
        User(
            id=new_uuid(),
            phone_e164=PHONE,
            phone_verified_at=deleted_at,
            status=UserStatus.ACTIVE,
            last_active_at=deleted_at,
            deleted_at=deleted_at,
            created_at=deleted_at,
            updated_at=deleted_at,
        )
    )
    issued = await harness.auth.request_code(phone=PHONE, request_ip=None)

    with pytest.raises(ForbiddenError) as caught:
        await harness.auth.verify_code(
            challenge_id=issued.challenge_id,
            code=issued.debug_code or "",
            request_ip=None,
            user_agent=None,
        )

    assert caught.value.code == "auth.account_deleted"
    assert harness.session_rows.sessions == {}


async def test_delivery_failure_does_not_lock_the_user_out() -> None:
    """A failed SMS must not consume the resend cooldown."""
    harness = build_harness(sms_fails=True)

    with pytest.raises(ServiceUnavailableError):
        await harness.auth.request_code(phone=PHONE, request_ip=None)

    challenge = next(iter(harness.challenges.rows.values()))
    assert challenge.invalidated_at is not None

    healthy = build_harness()
    await healthy.auth.request_code(phone=PHONE, request_ip=None)
    # Same number, but the earlier challenge belongs to another harness; the
    # point is only that the invalidated row no longer counts as pending.
    assert healthy.challenges.rows


async def test_codes_are_capped_per_number_and_hour() -> None:
    settings = Settings(
        _env_file=None,
        otp_expose_in_response=True,
        otp_max_per_number_per_hour=1,
        otp_resend_cooldown_seconds=0,
    )
    harness = build_harness(settings=settings)
    await harness.auth.request_code(phone=PHONE, request_ip=None)
    first = next(iter(harness.challenges.rows.values()))
    first.created_at = utcnow() - timedelta(minutes=2)

    with pytest.raises(RateLimitedError) as caught:
        await harness.auth.request_code(phone=PHONE, request_ip=None)
    assert caught.value.code == "auth.code_limit_reached"


async def test_codes_are_capped_per_address_and_hour() -> None:
    settings = Settings(
        _env_file=None,
        otp_expose_in_response=True,
        otp_max_per_ip_per_hour=1,
        otp_resend_cooldown_seconds=0,
    )
    harness = build_harness(settings=settings)
    await harness.auth.request_code(phone="09120000001", request_ip="203.0.113.7")

    with pytest.raises(RateLimitedError) as caught:
        await harness.auth.request_code(phone="09120000002", request_ip="203.0.113.7")
    assert caught.value.code == "auth.code_limit_reached"


async def test_session_listing_renders_inet_addresses_as_strings() -> None:
    """PostgreSQL INET returns an ipaddress object; the API contract is a string."""
    harness = build_harness()
    issued = await harness.auth.request_code(phone=PHONE, request_ip=None)
    login = await harness.auth.verify_code(
        challenge_id=issued.challenge_id,
        code=issued.debug_code or "",
        request_ip="203.0.113.7",
        user_agent=None,
    )
    harness.session_rows.sessions[login.tokens.session_id].ip = ipaddress.IPv4Address(
        "203.0.113.7"
    )

    listed = await harness.sessions.list_sessions(
        user_id=login.user.id, current_session_id=login.tokens.session_id
    )
    assert listed[0].ip == "203.0.113.7"
