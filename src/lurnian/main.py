"""Lurnian Backend application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from lurnian.api.errors import register_error_handlers
from lurnian.api.router import build_v1_router
from lurnian.core.config import get_settings, validate_production_settings
from lurnian.core.database import check_database_connection, dispose_db_engine
from lurnian.core.logging import setup_logging
from lurnian.modules.health import health_router

logger = logging.getLogger("lurnian.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle events."""
    settings = get_settings()
    setup_logging(log_level=settings.log_level)

    logger.info(
        "Starting %s [version: %s, env: %s]",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )

    # Startup is deliberately fail-open: an unavailable database must not crash
    # the process (and restart-loop it), it only leaves the service not ready.
    if not await check_database_connection():
        logger.warning(
            "Database is not reachable at startup; %s will serve health checks "
            "but report not ready until connectivity is restored",
            settings.app_name,
        )

    yield

    await dispose_db_engine()
    logger.info("Shutting down %s", settings.app_name)


def create_application() -> FastAPI:
    """Factory creating and configuring the FastAPI instance."""
    settings = get_settings()
    validate_production_settings(settings)

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    register_error_handlers(application)

    application.include_router(health_router)
    application.include_router(build_v1_router(), prefix=settings.api_v1_prefix)

    return application


app = create_application()
