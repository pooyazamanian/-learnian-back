"""Platform domain: administrative audit trail and the transactional outbox."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lurnian.core.database import Base
from lurnian.core.enums import ActorType, pg_enum


class AuditLog(Base):
    """Who changed what data, when, and from where.

    Distinct from ``security_events``: this is data accountability, that table
    feeds security logic. ``before_data``/``after_data`` must be redacted by the
    service before insert.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("char_length(action) BETWEEN 3 AND 100", name="action_length"),
        Index(
            "ix_audit_logs_entity",
            "entity_type",
            "entity_id",
            text("created_at DESC"),
        ),
        Index("ix_audit_logs_actor", "actor_user_id", text("created_at DESC")),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), primary_key=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    actor_type: Mapped[ActorType] = mapped_column(pg_enum(ActorType), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Text so both UUID and bigint identifiers fit.
    entity_id: Mapped[str | None] = mapped_column(Text)
    before_data: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    after_data: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OutboxEvent(Base):
    """Domain event written in the same transaction as the business change.

    No foreign keys on purpose: an event must survive deletion of its aggregate.
    Consumed rows may be pruned after their retention window.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "char_length(event_type) BETWEEN 3 AND 100", name="event_type_length"
        ),
        Index(
            "uq_outbox_events_dedupe_key",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
        Index(
            "ix_outbox_events_pending",
            "available_at",
            "id",
            postgresql_where=text("processed_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), primary_key=True
    )
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text)
