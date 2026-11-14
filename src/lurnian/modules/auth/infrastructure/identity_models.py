"""Identity domain: the root user record, external identities and credentials.

This module owns ``users``, ``user_identities``, ``user_credentials`` and
``verification_challenges``. Nothing here knows whether a user is premium or
how many review cards they have.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import BYTEA, INET
from sqlalchemy.orm import Mapped, mapped_column

from lurnian.core.database import Base
from lurnian.core.enums import (
    ChallengeChannel,
    ChallengePurpose,
    CredentialKind,
    IdentityProvider,
    UserStatus,
    pg_enum,
)
from lurnian.core.types import TimestampMixin, new_uuid


class User(Base, TimestampMixin):
    """Root identity record: the only table that says a user exists.

    Users are soft-deleted (``deleted_at``); financial and learning ledgers keep
    their foreign keys alive because the row never disappears.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "email IS NOT NULL OR phone_e164 IS NOT NULL",
            name="at_least_one_identifier",
        ),
        CheckConstraint(
            "email IS NULL OR email ~"
            " '^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$'",
            name="email_format",
        ),
        CheckConstraint(
            "phone_e164 IS NULL OR phone_e164 ~ '^\\+[1-9][0-9]{7,14}$'",
            name="phone_e164_format",
        ),
        # A deleted user may be "pending_deletion", but the flag alone is never
        # enough: the timestamp is the source of truth for soft deletion.
        CheckConstraint(
            "status <> 'pending_deletion' OR deleted_at IS NOT NULL",
            name="pending_deletion_requires_timestamp",
        ),
        Index(
            "ix_users_email_lower",
            func.lower(text("email")),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        Index(
            "ix_users_phone_e164",
            text("phone_e164"),
            unique=True,
            postgresql_where=text("phone_e164 IS NOT NULL"),
        ),
        Index(
            "ix_users_last_active_at",
            text("last_active_at"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    email: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phone_e164: Mapped[str | None] = mapped_column(Text)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus), nullable=False, server_default=text("'active'")
    )
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserIdentity(Base):
    """External identity (Google/Apple) linked to a user.

    Provider tokens are never stored; ``(provider, subject)`` is the only
    handle, and its unique constraint closes the duplicate-account race.
    """

    __tablename__ = "user_identities"
    __table_args__ = (
        CheckConstraint(
            "char_length(subject) BETWEEN 1 AND 255", name="subject_length"
        ),
        Index("ix_user_identities_user_id", "user_id"),
        Index(
            "ix_user_identities_provider_subject", "provider", "subject", unique=True
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[IdentityProvider] = mapped_column(
        pg_enum(IdentityProvider), nullable=False
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    email_at_provider: Mapped[str | None] = mapped_column(Text)
    email_verified: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserCredential(Base, TimestampMixin):
    """Local authentication factor: password, TOTP secret or recovery codes.

    Secrets are stored only in protected form (Argon2id hash for passwords and
    recovery codes, AES-256-GCM ciphertext for TOTP); the raw value never
    reaches the database.
    """

    __tablename__ = "user_credentials"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'password' AND secret_hash IS NOT NULL)"
            " OR (kind = 'recovery_codes' AND secret_hash IS NOT NULL)"
            " OR (kind = 'totp' AND secret_encrypted IS NOT NULL)",
            name="secret_present_for_kind",
        ),
        CheckConstraint("digits BETWEEN 6 AND 8", name="digits_range"),
        CheckConstraint("period_seconds BETWEEN 15 AND 120", name="period_range"),
        Index("ix_user_credentials_user_id", "user_id"),
        Index(
            "uq_user_credentials_active_password",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'password' AND revoked_at IS NULL"),
        ),
        Index(
            "uq_user_credentials_active_totp",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'totp' AND revoked_at IS NULL"),
        ),
        Index(
            "uq_user_credentials_active_recovery_codes",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'recovery_codes' AND revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[CredentialKind] = mapped_column(
        pg_enum(CredentialKind), nullable=False
    )
    secret_hash: Mapped[str | None] = mapped_column(Text)
    secret_encrypted: Mapped[bytes | None] = mapped_column(BYTEA)
    algorithm: Mapped[str | None] = mapped_column(Text, server_default=text("'SHA1'"))
    digits: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("6")
    )
    period_seconds: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("30")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VerificationChallenge(Base):
    """One-time code or link, usable before an account exists.

    The code itself is never stored: ``code_hash`` (HMAC-SHA256 with a
    server-side pepper) is compared in constant time.
    """

    __tablename__ = "verification_challenges"
    __table_args__ = (
        CheckConstraint(
            "attempts BETWEEN 0 AND max_attempts", name="attempts_within_limit"
        ),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="consumed_after_creation",
        ),
        Index(
            "ix_verification_challenges_lookup",
            "destination",
            "purpose",
            text("created_at DESC"),
        ),
        Index(
            "ix_verification_challenges_pending",
            "destination",
            "purpose",
            postgresql_where=text("consumed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    channel: Mapped[ChallengeChannel] = mapped_column(
        pg_enum(ChallengeChannel), nullable=False
    )
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[ChallengePurpose] = mapped_column(
        pg_enum(ChallengePurpose), nullable=False
    )
    code_hash: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("5")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_ip: Mapped[str | None] = mapped_column(INET)
