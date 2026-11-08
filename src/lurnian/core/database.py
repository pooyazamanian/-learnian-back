"""Async database engine, session factory and readiness probe."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Final

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from lurnian.core.config import Settings, get_settings

logger = logging.getLogger("lurnian.core.database")

NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by the models of every module."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _create_engine(settings: Settings) -> AsyncEngine:
    """Build the async engine from settings.

    Connection pooling is provided by SQLAlchemy itself; no external pooler is
    configured. Server-side timeouts are passed as libpq options so a stuck
    statement can never hold a pooled connection indefinitely.
    """
    return create_async_engine(
        settings.database_url.get_secret_value(),
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=settings.db_pool_pre_ping,
        connect_args={
            "connect_timeout": settings.db_connect_timeout,
            "options": (
                f"-c statement_timeout={settings.db_statement_timeout_ms}"
                f" -c lock_timeout={settings.db_lock_timeout_ms}"
            ),
        },
    )


def get_engine() -> AsyncEngine:
    """Return the process-wide engine, creating it on first use."""
    global _engine  # process-wide lazy singleton

    if _engine is None:
        _engine = _create_engine(get_settings())
        logger.debug("Database engine created")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory bound to the process-wide engine."""
    global _session_factory  # process-wide lazy singleton

    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Provide a request-scoped session.

    Only the session lifecycle is managed here. Transaction boundaries belong to
    the service/use-case layer, so this dependency never commits. The rollback
    below is a safety net for exceptions that escape a service.
    """
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_database_connection() -> bool:
    """Return whether a trivial query succeeds within the ready timeout.

    Never raises: readiness probing must not turn a database outage into an
    application error, and no driver details are exposed to callers.
    """
    try:
        async with asyncio.timeout(get_settings().db_ready_timeout):
            async with get_engine().connect() as connection:
                await connection.execute(text("SELECT 1"))
    except Exception as exc:
        # Probes are polled frequently, so the warning stays concise and the
        # full driver detail is only emitted at DEBUG level.
        logger.warning("Database readiness check failed: %s", type(exc).__name__)
        logger.debug("Readiness failure details", exc_info=True)
        return False
    return True


async def dispose_db_engine() -> None:
    """Dispose the engine and drop the cached factories."""
    global _engine, _session_factory  # process-wide lazy singletons

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.debug("Database engine disposed")
