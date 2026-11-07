"""Pytest shared fixtures configuration."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from lurnian.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Provide an asynchronous HTTP test client bound to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        yield test_client
