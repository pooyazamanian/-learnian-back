"""One error contract, one place that produces it.

Every failure leaves the API as::

    {"error": {"code": "...", "message": "...", "request_id": "...", "details": {...}}}

Domain code raises :class:`~lurnian.core.exceptions.AppError`; framework errors
(validation, unknown route, method) and database integrity failures are mapped
here, so a route never builds an error body itself. ``request_id`` is echoed in
the ``X-Request-ID`` header and in logs, which is what makes a 500 traceable.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from lurnian.core.config import get_settings
from lurnian.core.exceptions import AppError

logger = logging.getLogger("lurnian.api.errors")

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

_HTTP_CODES: dict[int, str] = {
    400: "invalid_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    503: "unavailable",
}


def current_request_id() -> str:
    """Return the correlation id of the request being handled."""
    return _request_id.get()


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the single error envelope used by every handler below."""
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": current_request_id(),
    }
    if details:
        error["details"] = details
    return JSONResponse(
        status_code=status_code, content={"error": error}, headers=headers
    )


async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    """Render a domain error without leaking internals."""
    headers: dict[str, str] = {}
    retry_after = exc.details.get("retry_after")
    if exc.status_code == 429 and isinstance(retry_after, int):
        # Give well-behaved clients a machine-readable wait time.
        headers["Retry-After"] = str(max(1, retry_after))
    return _error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details or None,
        headers=headers or None,
    )


async def _handle_validation_error(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    """Report every invalid field in one flat, client-friendly list."""
    fields = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())),
            "message": error.get("msg", "Invalid value"),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]
    return _error_response(
        status_code=422,
        code="validation_error",
        message="The request body or parameters are invalid",
        details={"fields": fields},
    )


async def _handle_http_exception(
    _: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Keep framework errors (404, 405, ...) inside the same envelope."""
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return _error_response(
        status_code=exc.status_code,
        code=_HTTP_CODES.get(exc.status_code, "http_error"),
        message=message,
    )


async def _handle_integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
    """Translate an unhandled constraint violation into a 409.

    Only the SQLSTATE and driver exception type are logged: the raw driver
    message can echo parameter values, which may include personal data.
    """
    logger.warning(
        "Unhandled integrity error [sqlstate=%s, driver=%s]",
        getattr(exc.orig, "sqlstate", "unknown"),
        type(exc.orig).__name__,
    )
    return _error_response(
        status_code=409,
        code="conflict",
        message="The request conflicts with existing data",
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Log the stack trace and return an opaque 500."""
    logger.exception(
        "Unhandled error [request_id=%s] %s %s",
        current_request_id(),
        request.method,
        request.url.path,
    )
    return _error_response(
        status_code=500,
        code="internal_error",
        message="Unexpected error",
    )


def register_error_handlers(application: FastAPI) -> None:
    """Attach request correlation and every exception handler to the app."""
    if not getattr(application.state, "request_id_middleware", False):

        @application.middleware("http")
        async def add_request_id(request: Request, call_next: Any) -> Any:
            """Give every request an id, echo it, and keep auth replies uncached.

            The context variable is intentionally not reset: the 500 handler runs
            outside this middleware, and resetting it first would replace the
            correlation id with ``-`` exactly when it matters most.
            """
            request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
            _request_id.set(request_id)
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            if request.url.path.startswith(f"{get_settings().api_v1_prefix}/auth"):
                # Tokens and phone numbers must never sit in a shared cache.
                response.headers["Cache-Control"] = "no-store"
                response.headers["Pragma"] = "no-cache"
            return response

        application.state.request_id_middleware = True

    application.add_exception_handler(AppError, _handle_app_error)
    application.add_exception_handler(RequestValidationError, _handle_validation_error)
    application.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    application.add_exception_handler(IntegrityError, _handle_integrity_error)
    application.add_exception_handler(Exception, _handle_unexpected_error)
