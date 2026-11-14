"""Security domain: devices, sessions, refresh tokens, security events and roles.

Access tokens are intentionally absent: they are stateless and never stored.
Only sessions and one-time refresh tokens live here, which is what makes
"log out everywhere" and reuse detection possible.
"""

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
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import BYTEA, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from lurnian.core.database import Base
from lurnian.core.enums import (
    AuthMethod,
    DevicePlatform,
    PushProvider,
    SecuritySeverity,
    SessionRevokedReason,
    pg_enum,
)
from lurnian.core.types import TimestampMixin, new_uuid


class UserDevice(Base):
    """Known device of a user with the push token it should be reached on."""

    __tablename__ = "user_devices"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "fingerprint_hash", name="uq_user_devices_user_fingerprint"
        ),
        CheckConstraint(
            "push_token IS NULL OR push_provider IS NOT NULL",
            name="push_provider_required",
        ),
        Index("ix_user_devices_user_id", "user_id"),
        Index(
            "ix_user_devices_active_user",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    fingerprint_hash: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[DevicePlatform] = mapped_column(
        pg_enum(DevicePlatform), nullable=False
    )
    display_name: Mapped[str | None] = mapped_column(Text)
    app_version: Mapped[str | None] = mapped_column(Text)
    # A push token is a capability: whoever holds it can push to the device.
    push_token: Mapped[str | None] = mapped_column(Text)
    push_provider: Mapped[PushProvider | None] = mapped_column(pg_enum(PushProvider))
    push_token_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    trusted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    """One successful login: the unit of immediate access revocation."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        CheckConstraint(
            "absolute_expires_at > created_at", name="absolute_expiry_after_creation"
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_reason IS NOT NULL",
            name="revocation_reason_present",
        ),
        Index("ix_user_sessions_user_created", "user_id", text("created_at DESC")),
        Index(
            "ix_user_sessions_active_user",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_devices.id", ondelete="SET NULL")
    )
    auth_method: Mapped[AuthMethod] = mapped_column(pg_enum(AuthMethod), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    absolute_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[SessionRevokedReason | None] = mapped_column(
        pg_enum(SessionRevokedReason)
    )


class RefreshToken(Base):
    """Single-use rotating refresh token; only its SHA-256 hash is stored.

    Reuse of an already-used token revokes the whole ``family_id`` chain, so a
    stolen token cannot outlive one rotation.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint("expires_at > issued_at", name="expiry_after_issue"),
        CheckConstraint(
            "used_at IS NULL OR used_at >= issued_at", name="used_after_issue"
        ),
        Index("ix_refresh_tokens_session_id", "session_id"),
        Index("ix_refresh_tokens_family_id", "family_id"),
        Index(
            "uq_refresh_tokens_active_session",
            "session_id",
            unique=True,
            postgresql_where=text("used_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_sessions.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(BYTEA, nullable=False, unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[SessionRevokedReason | None] = mapped_column(
        pg_enum(SessionRevokedReason)
    )


class SecurityEvent(Base):
    """Append-only security signal; the input of lockout and alerting logic."""

    __tablename__ = "security_events"
    __table_args__ = (
        CheckConstraint(
            "char_length(event_type) BETWEEN 3 AND 100", name="event_type_length"
        ),
        Index("ix_security_events_user_created", "user_id", text("created_at DESC")),
        Index("ix_security_events_type_created", "event_type", text("created_at DESC")),
        Index(
            "ix_security_events_critical_created",
            "created_at",
            postgresql_where=text("severity = 'critical'"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), primary_key=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    # Event types grow with the product, so they are text rather than an enum.
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[SecuritySeverity] = mapped_column(
        pg_enum(SecuritySeverity), nullable=False, server_default=text("'info'")
    )
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserSecuritySettings(Base, TimestampMixin):
    """Per-user security policy. Whether TOTP is enrolled lives in credentials."""

    __tablename__ = "user_security_settings"
    __table_args__ = (
        CheckConstraint(
            "session_idle_timeout_minutes IS NULL"
            " OR session_idle_timeout_minutes BETWEEN 5 AND 43200",
            name="idle_timeout_range",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    two_factor_required: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    login_alerts_enabled: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("true")
    )
    session_idle_timeout_minutes: Mapped[int | None] = mapped_column(SmallInteger)


class Role(Base):
    """Staff/operational role. Consumer access is entitlement, never a role."""

    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,31}$'", name="code_format"),
        Index("ix_roles_code", "code", unique=True),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, Identity(always=False), primary_key=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserRole(Base):
    """Role assignment with the granting admin and an optional expiry."""

    __tablename__ = "user_roles"
    __table_args__ = (
        CheckConstraint(
            "expires_at IS NULL OR expires_at > granted_at",
            name="expiry_after_grant",
        ),
        Index("ix_user_roles_role_id", "role_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
