"""Health and system inspection router."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from lurnian.core.config import Settings, get_settings
from lurnian.core.database import check_database_connection
from lurnian.modules.health.schemas import (
    HealthResponse,
    ReadinessResponse,
    RootResponse,
)

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
    "/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ReadinessResponse,
            "description": "Database dependency is not reachable.",
        }
    },
    summary="Readiness Check Endpoint",
    description=(
        "Check whether the service is ready to receive traffic, including "
        "database connectivity."
    ),
)
async def readiness_check(
    database_ready: Annotated[bool, Depends(check_database_connection)],
) -> JSONResponse:
    """Return readiness status and database connectivity."""
    payload = ReadinessResponse(
        status="ready" if database_ready else "not_ready",
        database="ok" if database_ready else "unavailable",
    )
    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if database_ready
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content=payload.model_dump(),
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
