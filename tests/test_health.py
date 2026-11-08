"""Tests for root and health check endpoints."""

import pytest
from httpx import AsyncClient

from lurnian.core.database import check_database_connection
from lurnian.main import app


@pytest.mark.asyncio
async def test_read_root_endpoint(client: AsyncClient) -> None:
    """Verify that GET / returns 200 and expected payload."""
    response = await client.get("/")
    assert response.status_code == 200

    payload = response.json()
    assert "message" in payload
    assert "version" in payload
    assert payload["docs_url"] == "/docs"


@pytest.mark.asyncio
async def test_readiness_endpoint_ready(client: AsyncClient) -> None:
    """Verify that GET /ready returns 200 when the database is reachable."""
    app.dependency_overrides[check_database_connection] = lambda: True
    try:
        response = await client.get("/ready")
    finally:
        app.dependency_overrides.pop(check_database_connection, None)

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


@pytest.mark.asyncio
async def test_readiness_endpoint_not_ready(client: AsyncClient) -> None:
    """Verify that GET /ready returns 503 while the database is unavailable."""
    app.dependency_overrides[check_database_connection] = lambda: False
    try:
        response = await client.get("/ready")
    finally:
        app.dependency_overrides.pop(check_database_connection, None)

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}


@pytest.mark.asyncio
async def test_health_check_endpoint(client: AsyncClient) -> None:
    """Verify that GET /health returns 200 and healthy status."""
    response = await client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app_name"] == "Lurnian Backend"
    assert payload["environment"] in ("development", "staging", "production")
    assert "version" in payload
