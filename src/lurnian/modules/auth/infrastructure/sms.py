"""SMS adapters.

There is no provider yet, so the development adapter writes the message to the
log and masks the receiver. Swapping in a real provider means adding one class
here and one line in the dependency wiring - nothing else changes.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("lurnian.auth.sms")


class LoggingSmsSender:
    """Deliver OTPs to the application log (development only)."""

    def __init__(self, *, include_code: bool) -> None:
        self._include_code = include_code
        if not include_code:
            logger.warning(
                "No SMS provider is configured; sign-in codes will not reach users"
            )

    async def send_code(self, *, phone: str, code: str) -> None:
        """Record the delivery attempt without exposing the full number."""
        if self._include_code:
            logger.info("SMS OTP for %s: %s", _mask(phone), code)
        else:
            logger.info("SMS OTP dispatch attempted for %s", _mask(phone))


def _mask(phone: str) -> str:
    """Show only the last four digits of a phone number."""
    return f"***{phone[-4:]}"
