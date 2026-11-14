"""Time helpers shared by the auth use cases.

Kept in one place so every comparison uses the same timezone rule: the database
always returns aware UTC datetimes, while a freshly built object or a test double
may be naive.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Treat a naive datetime as UTC and normalize anything else to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_expired(expires_at: datetime, *, now: datetime) -> bool:
    """Return whether ``expires_at`` has been reached by ``now``."""
    return as_utc(expires_at) <= now


def seconds_until(target: datetime, *, now: datetime) -> int:
    """Return whole seconds left until ``target``, never negative."""
    remaining = (as_utc(target) - now).total_seconds()
    return max(0, math.ceil(remaining))
