"""Tests for root and health check endpoints."""

import pytest
from httpx import AsyncClient


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
async def test_health_check_endpoint(client: AsyncClient) -> None:
    """Verify that GET /health returns 200 and healthy status."""
    response = await client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app_name"] == "Lurnian Backend"
    assert payload["environment"] in ("development", "staging", "production")
    assert "version" in payload
