"""HTTP contract tests that stop before touching PostgreSQL.

Only paths that fail during validation or authentication are covered here; the
database-backed flows live in ``test_auth_services.py`` behind in-memory ports.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from lurnian.modules.review.schemas import AnswerRequest


async def test_review_queue_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/review/queue")
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "unauthenticated"
    assert error["request_id"]


async def test_logout_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_garbage_bearer_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"}
    )
    assert response.status_code == 401


async def test_invalid_phone_fails_before_any_database_work(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/auth/otp/request", json={"phone": "not-a-phone"}
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_phone"
    assert response.headers["x-request-id"] == error["request_id"]


async def test_short_phone_never_reaches_the_service(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/otp/request", json={"phone": "12"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_otp_code_must_be_numeric(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/otp/verify",
        json={"challenge_id": str(uuid.uuid4()), "code": "12ab"},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"]["fields"][0]["field"].endswith("code")


async def test_password_endpoints_are_gone(client: AsyncClient) -> None:
    """v1 signs in with a phone number only; the old routes must not linger."""
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "learner@example.com", "password": "long-enough-password"},
    )
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "learner@example.com", "password": "long-enough-password"},
    )
    assert login.status_code == 404
    assert register.status_code == 404


async def test_unknown_route_uses_the_same_error_envelope(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/auth/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"]


def test_answer_rating_must_be_on_the_four_point_scale() -> None:
    """Rating is a four-point scale; anything else never reaches the service."""
    with pytest.raises(ValidationError):
        AnswerRequest(card_id=uuid.uuid4(), rating=7, idempotency_key="answer-0001")


def test_answer_requires_an_idempotency_key() -> None:
    """A review without a key could be recorded twice by a retry."""
    with pytest.raises(ValidationError):
        AnswerRequest(card_id=uuid.uuid4(), rating=3, idempotency_key="short")
