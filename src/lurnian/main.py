"""Lurnian Backend application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from lurnian.core.config import get_settings
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
    yield
    logger.info("Shutting down %s", settings.app_name)


def create_application() -> FastAPI:
    """Factory creating and configuring the FastAPI instance."""
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Register modules routers
    application.include_router(health_router)

    return application


app = create_application()
