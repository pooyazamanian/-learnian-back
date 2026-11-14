"""Domain errors and the HTTP status each one maps to.

Services raise these instead of FastAPI's ``HTTPException`` so the use-case
layer stays framework-agnostic and testable without an HTTP request. Exactly one
module (``lurnian.api.errors``) turns them into responses.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for errors that are safe to expose to API clients."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str = "Unexpected error",
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        #: Extra, client-safe context such as ``attempts_left``.
        self.details: dict[str, Any] = dict(details or {})
        if code is not None:
            self.code = code


class ValidationError(AppError):
    """The request is well-formed but violates a business rule."""

    status_code = 400
    code = "invalid_request"


class AuthenticationError(AppError):
    """Credentials or tokens are missing, invalid or expired."""

    status_code = 401
    code = "unauthenticated"


class ForbiddenError(AppError):
    """The caller is authenticated but not allowed to perform the action."""

    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    """The addressed resource does not exist for this caller."""

    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    """The request conflicts with the current state (or lost a race)."""

    status_code = 409
    code = "conflict"


class RateLimitedError(AppError):
    """The caller asked too often and must wait before retrying."""

    status_code = 429
    code = "rate_limited"


class ServiceUnavailableError(AppError):
    """A required dependency is not configured or temporarily unavailable."""

    status_code = 503
    code = "unavailable"
