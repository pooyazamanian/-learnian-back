"""Notification domain: channel preferences, scheduled reminders, delivery log.

Reminders are derived from review events through the outbox and coalesced to
one row per user per day (``dedupe_key``), not one row per card. Notification
text is not stored: it is rendered at send time from current data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from lurnian.core.database import Base
from lurnian.core.types import TimestampMixin, new_uuid

_CATEGORIES = (
    "'review_reminder', 'streak', 'subscription', 'product_updates', 'security'"
)
_ACTIVE_CHANNELS = "'push', 'email', 'sms'"


class NotificationPreference(Base):
    """Channel x category matrix; absence of a row means "enabled by default"."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        CheckConstraint(f"category IN ({_CATEGORIES})", name="category_allowed"),
        CheckConstraint(f"channel IN ({_ACTIVE_CHANNELS})", name="channel_allowed"),
        CheckConstraint(
            "NOT (category = 'security' AND is_enabled = false)",
            name="security_always_enabled",
        ),
        CheckConstraint(
            "(quiet_hours_start IS NULL) = (quiet_hours_end IS NULL)",
            name="quiet_hours_complete",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    category: Mapped[str] = mapped_column(Text, primary_key=True)
    channel: Mapped[str] = mapped_column(Text, primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("true")
    )
    quiet_hours_start: Mapped[time | None] = mapped_column(Time)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ScheduledNotification(Base, TimestampMixin):
    """A reminder waiting to be delivered, with retry and dedupe state."""

    __tablename__ = "scheduled_notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "dedupe_key", name="uq_scheduled_notifications_user_dedupe"
        ),
        CheckConstraint(f"category IN ({_CATEGORIES})", name="category_allowed"),
        CheckConstraint("channel IN ('push', 'email')", name="channel_allowed"),
        CheckConstraint(
            "status IN ('pending', 'queued', 'sending', 'sent',"
            " 'canceled', 'failed', 'dead')",
            name="status_allowed",
        ),
        CheckConstraint("attempts <= max_attempts", name="attempts_within_limit"),
        CheckConstraint(
            "status <> 'sent' OR sent_at IS NOT NULL", name="sent_has_timestamp"
        ),
        Index(
            "ix_scheduled_notifications_dispatch",
            "status",
            "deliver_after",
            postgresql_where=text("status IN ('pending', 'queued')"),
        ),
        Index("ix_scheduled_notifications_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_devices.id", ondelete="SET NULL")
    )
    review_card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_cards.id", ondelete="CASCADE")
    )
    trigger_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    deliver_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("5")
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationHistory(Base):
    """Append-only delivery log; delivery and user attention are separate."""

    __tablename__ = "notification_history"
    __table_args__ = (
        CheckConstraint(f"channel IN ({_ACTIVE_CHANNELS})", name="channel_allowed"),
        CheckConstraint(
            "delivery_status IN"
            " ('accepted', 'delivered', 'failed', 'bounced', 'suppressed')",
            name="delivery_status_allowed",
        ),
        CheckConstraint(
            "delivery_status <> 'delivered' OR delivered_at IS NOT NULL",
            name="delivered_has_timestamp",
        ),
        Index(
            "ix_notification_history_user_created",
            "user_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_notification_history_scheduled_notification_id",
            "scheduled_notification_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    scheduled_notification_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "scheduled_notifications.id",
            ondelete="SET NULL",
            name="fk_notification_history_scheduled_notification",
        )
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    delivery_status: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
