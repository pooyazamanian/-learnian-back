"""Phone sign-in use cases: request a code, verify it, open a session.

Both identifiers (new and returning users) take the same path; the only
difference is whether ``users`` gets a row. Nothing here knows about HTTP, and
nothing else in the codebase issues OTPs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from lurnian.core.config import Settings
from lurnian.core.enums import (
    AuthMethod,
    ChallengeChannel,
    ChallengePurpose,
    UserStatus,
)
from lurnian.core.exceptions import (
    AuthenticationError,
    ForbiddenError,
    RateLimitedError,
    ServiceUnavailableError,
)
from lurnian.core.security import (
    generate_numeric_code,
    hash_numeric_code,
    numeric_code_matches,
)
from lurnian.modules.auth.application.dto import (
    IssuedChallenge,
    LoginResult,
)
from lurnian.modules.auth.application.ports import (
    AccountDefaults,
    ChallengeRepository,
    SmsSender,
    UnitOfWork,
    UserRepository,
)
from lurnian.modules.auth.application.session_service import SessionService
from lurnian.modules.auth.domain.clock import (
    is_expired,
    seconds_until,
    utcnow,
)
from lurnian.modules.auth.domain.phone import normalize_phone
from lurnian.modules.auth.infrastructure.identity_models import VerificationChallenge

logger = logging.getLogger("lurnian.auth.otp")


class AuthService:
    """Single responsibility: turn a phone number into a live session."""

    def __init__(
        self,
        *,
        users: UserRepository,
        challenges: ChallengeRepository,
        sessions: SessionService,
        defaults: AccountDefaults,
        sms: SmsSender,
        uow: UnitOfWork,
        settings: Settings,
    ) -> None:
        self._users = users
        self._challenges = challenges
        self._sessions = sessions
        self._defaults = defaults
        self._sms = sms
        self._uow = uow
        self._settings = settings

    async def request_code(
        self, *, phone: str, request_ip: str | None
    ) -> IssuedChallenge:
        """Create a one-time code for ``phone`` and send it by SMS."""
        normalized = normalize_phone(
            phone, default_country_code=self._settings.default_phone_country_code
        )
        now = utcnow()
        await self._enforce_request_limits(normalized, request_ip, now=now)
        await self._enforce_resend_cooldown(normalized, now=now)
        await self._challenges.invalidate_pending(
            normalized, purpose=ChallengePurpose.LOGIN, now=now
        )

        code = generate_numeric_code(self._settings.otp_length)
        challenge = VerificationChallenge(
            channel=ChallengeChannel.SMS,
            destination=normalized,
            purpose=ChallengePurpose.LOGIN,
            code_hash=hash_numeric_code(
                code, pepper=self._settings.otp_pepper.get_secret_value()
            ),
            attempts=0,
            max_attempts=self._settings.otp_max_attempts,
            created_at=now,
            expires_at=now + timedelta(seconds=self._settings.otp_ttl_seconds),
            request_ip=request_ip,
        )
        await self._challenges.add(challenge)
        # Commit before delivery: the code must be verifiable the moment the
        # user can read it.
        await self._uow.commit()

        try:
            await self._deliver(phone=normalized, code=code)
        except ServiceUnavailableError:
            # Otherwise the user is locked out by the cooldown for a code that
            # never arrived.
            challenge.invalidated_at = utcnow()
            await self._uow.commit()
            raise
        return IssuedChallenge(
            challenge_id=challenge.id,
            expires_in=self._settings.otp_ttl_seconds,
            resend_after=self._settings.otp_resend_cooldown_seconds,
            debug_code=self._debug_code(code),
        )

    async def verify_code(
        self,
        *,
        challenge_id: uuid.UUID,
        code: str,
        request_ip: str | None,
        user_agent: str | None,
    ) -> LoginResult:
        """Consume a code and return the user with a fresh token pair."""
        now = utcnow()
        challenge = await self._challenges.get_for_update(challenge_id)
        if (
            challenge is None
            or challenge.purpose is not ChallengePurpose.LOGIN
            or challenge.consumed_at is not None
            or challenge.invalidated_at is not None
        ):
            raise AuthenticationError(
                "This code is no longer valid; request a new one",
                code="auth.code_invalid",
            )

        if is_expired(challenge.expires_at, now=now):
            raise AuthenticationError(
                "This code has expired; request a new one",
                code="auth.code_expired",
            )

        if challenge.attempts >= challenge.max_attempts:
            raise RateLimitedError(
                "Too many incorrect attempts; request a new code",
                code="auth.too_many_attempts",
            )

        if not numeric_code_matches(
            code,
            challenge.code_hash,
            pepper=self._settings.otp_pepper.get_secret_value(),
        ):
            challenge.attempts += 1
            await self._uow.commit()
            raise AuthenticationError(
                "Incorrect code",
                code="auth.invalid_code",
                details={
                    "attempts_left": max(0, challenge.max_attempts - challenge.attempts)
                },
            )

        challenge.consumed_at = now
        user, created = await self._users.create_or_get(challenge.destination, now=now)
        if created:
            await self._defaults.create_for(user.id, now=now)

        if user.deleted_at is not None:
            # The unique index still owns the number, so this is the only way a
            # soft-deleted account can reach the sign-in path.
            await self._uow.commit()
            raise ForbiddenError(
                "This account is not available", code="auth.account_deleted"
            )

        if user.status is not UserStatus.ACTIVE:
            # The code is still burned: a disabled account must not keep a live
            # challenge that a later request could replay.
            await self._uow.commit()
            raise ForbiddenError(
                "This account cannot sign in", code="auth.account_disabled"
            )

        await self._users.touch_login(user, now=now)
        tokens = await self._sessions.start(
            user_id=user.id,
            method=AuthMethod.SMS_OTP,
            ip=request_ip,
            user_agent=user_agent,
        )
        await self._uow.commit()
        return LoginResult(user=user, is_new_user=created, tokens=tokens)

    async def _enforce_request_limits(
        self, destination: str, request_ip: str | None, *, now: datetime
    ) -> None:
        """Cap hourly volume per number and per address.

        The 60-second cooldown stops a double tap; these ceilings stop a script
        from turning the endpoint into an SMS bomb and a cost amplifier.
        """
        window_start = now - timedelta(hours=1)
        for_destination = await self._challenges.count_for_destination(
            destination, since=window_start
        )
        if for_destination >= self._settings.otp_max_per_number_per_hour:
            raise RateLimitedError(
                "Too many codes requested for this number; try again later",
                code="auth.code_limit_reached",
            )
        if request_ip is None:
            return
        for_address = await self._challenges.count_for_ip(
            request_ip, since=window_start
        )
        if for_address >= self._settings.otp_max_per_ip_per_hour:
            raise RateLimitedError(
                "Too many codes requested from this address; try again later",
                code="auth.code_limit_reached",
            )

    async def _enforce_resend_cooldown(
        self, destination: str, *, now: datetime
    ) -> None:
        """Refuse a second code before the cooldown ends."""
        pending = await self._challenges.latest_pending(
            destination, ChallengePurpose.LOGIN
        )
        if pending is None:
            return
        retry_after = seconds_until(
            pending.created_at
            + timedelta(seconds=self._settings.otp_resend_cooldown_seconds),
            now=now,
        )
        if retry_after > 0:
            raise RateLimitedError(
                "A code was just sent; wait before requesting another",
                code="auth.code_cooldown",
                details={"retry_after": retry_after},
            )

    async def _deliver(self, *, phone: str, code: str) -> None:
        """Send the code, turning a delivery failure into a clean 503."""
        try:
            await self._sms.send_code(phone=phone, code=code)
        except Exception as exc:
            logger.warning("OTP delivery failed: %s", type(exc).__name__)
            raise ServiceUnavailableError(
                "Code delivery is temporarily unavailable", code="auth.sms_failed"
            ) from exc

    def _debug_code(self, code: str) -> str | None:
        """Expose the code only for local development, never otherwise."""
        if (
            self._settings.environment == "development"
            and self._settings.otp_expose_in_response
        ):
            return code
        return None
