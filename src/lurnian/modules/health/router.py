"""Health and system inspection router."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from lurnian.core.config import Settings, get_settings
from lurnian.modules.health.schemas import HealthResponse, RootResponse

router = APIRouter(tags=["Health & Status"])


@router.get(
    "/",
    response_model=RootResponse,
    status_code=status.HTTP_200_OK,
    summary="Root Endpoint",
    description="Returns welcome message and API documentation entry point.",
)
async def read_root(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RootResponse:
    """Return basic API info."""
    return RootResponse(
        message=f"Welcome to {settings.app_name}",
        version=settings.app_version,
        docs_url="/docs",
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health Check Endpoint",
    description="Check the operational health and environment of the service.",
)
async def health_check(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Return service health status and environment."""
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.environment,
        version=settings.app_version,
    )
