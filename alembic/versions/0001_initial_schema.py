"""Initial schema: 38 tables and 31 enum types.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-10

The DDL is written explicitly (rather than generated at runtime from the
metadata) so that ``alembic upgrade head --sql`` stays deterministic and the
baseline can be reviewed. Enum types are created first, because every table
column references them; constraint and index names match
``NAMING_CONVENTION`` in ``lurnian.core.database`` so later autogenerate runs
see no spurious drops.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from lurnian.core.enums import (
    ENUM_VALUES,
    ActorType,
    AuthMethod,
    BillingPeriod,
    CefrLevel,
    ChallengeChannel,
    ChallengePurpose,
    CredentialKind,
    DeckVisibility,
    DevicePlatform,
    EntitlementSource,
    ExampleSource,
    FeatureValueType,
    FsrsParameterSource,
    FsrsState,
    IdentityProvider,
    OrderStatus,
    PartOfSpeech,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
    PlanTier,
    PushProvider,
    ReviewCardMode,
    SecuritySeverity,
    SessionRevokedReason,
    SubscriptionStatus,
    TextDirection,
    ThemePreference,
    UserStatus,
    UserVocabularySource,
    UserVocabularyStatus,
    pg_enum,
)

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

NOW = sa.text("now()")


def _ts(name: str, *, nullable: bool = False) -> sa.Column:
    """Return a ``TIMESTAMPTZ`` column."""
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _audit_timestamps() -> tuple[sa.Column, sa.Column]:
    """Return the standard ``created_at`` / ``updated_at`` pair."""
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
    )


def upgrade() -> None:
    """Create enum types, then all tables, indexes and constraints."""

    for name, values in ENUM_VALUES.items():
        literals = ", ".join(f"'{value}'" for value in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({literals})")

    # --- D1: Identity -------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        _ts("email_verified_at", nullable=True),
        sa.Column("phone_e164", sa.Text(), nullable=True),
        _ts("phone_verified_at", nullable=True),
        sa.Column(
            "status",
            pg_enum(UserStatus),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        _ts("last_active_at", nullable=True),
        *_audit_timestamps(),
        _ts("deleted_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.CheckConstraint(
            "email IS NOT NULL OR phone_e164 IS NOT NULL",
            name="ck_users_at_least_one_identifier",
        ),
        sa.CheckConstraint(
            "email IS NULL OR email ~ '^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$'",
            name="ck_users_email_format",
        ),
        sa.CheckConstraint(
            "phone_e164 IS NULL OR phone_e164 ~ '^\\+[1-9][0-9]{7,14}$'",
            name="ck_users_phone_e164_format",
        ),
        sa.CheckConstraint(
            "status <> 'pending_deletion' OR deleted_at IS NOT NULL",
            name="ck_users_pending_deletion_requires_timestamp",
        ),
    )
    op.create_index(
        "ix_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "ix_users_phone_e164",
        "users",
        ["phone_e164"],
        unique=True,
        postgresql_where=sa.text("phone_e164 IS NOT NULL"),
    )
    op.create_index(
        "ix_users_last_active_at",
        "users",
        ["last_active_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.SmallInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_system", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.CheckConstraint(
            "code ~ '^[a-z][a-z0-9_]{1,31}$'", name="ck_roles_code_format"
        ),
    )
    op.create_index("ix_roles_code", "roles", ["code"], unique=True)

    op.create_table(
        "languages",
        sa.Column("id", sa.SmallInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("bcp47", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_native", sa.Text(), nullable=True),
        sa.Column("direction", pg_enum(TextDirection), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "sort_order", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_languages"),
    )
    op.create_index("ix_languages_code", "languages", ["code"], unique=True)
    op.create_index("ix_languages_bcp47", "languages", ["bcp47"], unique=True)

    op.create_table(
        "user_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", pg_enum(IdentityProvider), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("email_at_provider", sa.Text(), nullable=True),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        _ts("last_login_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_user_identities"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_identities_user_id_users",
        ),
        sa.CheckConstraint(
            "char_length(subject) BETWEEN 1 AND 255",
            name="ck_user_identities_subject_length",
        ),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])
    op.create_index(
        "ix_user_identities_provider_subject",
        "user_identities",
        ["provider", "subject"],
        unique=True,
    )

    op.create_table(
        "user_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", pg_enum(CredentialKind), nullable=False),
        sa.Column("secret_hash", sa.Text(), nullable=True),
        sa.Column("secret_encrypted", postgresql.BYTEA(), nullable=True),
        sa.Column(
            "algorithm", sa.Text(), nullable=True, server_default=sa.text("'SHA1'")
        ),
        sa.Column(
            "digits", sa.SmallInteger(), nullable=False, server_default=sa.text("6")
        ),
        sa.Column(
            "period_seconds",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("30"),
        ),
        _ts("confirmed_at", nullable=True),
        _ts("last_used_at", nullable=True),
        *_audit_timestamps(),
        _ts("revoked_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_user_credentials"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_credentials_user_id_users",
        ),
        sa.CheckConstraint(
            "(kind = 'password' AND secret_hash IS NOT NULL)"
            " OR (kind = 'recovery_codes' AND secret_hash IS NOT NULL)"
            " OR (kind = 'totp' AND secret_encrypted IS NOT NULL)",
            name="ck_user_credentials_secret_present_for_kind",
        ),
        sa.CheckConstraint(
            "digits BETWEEN 6 AND 8", name="ck_user_credentials_digits_range"
        ),
        sa.CheckConstraint(
            "period_seconds BETWEEN 15 AND 120",
            name="ck_user_credentials_period_range",
        ),
    )
    op.create_index("ix_user_credentials_user_id", "user_credentials", ["user_id"])
    op.create_index(
        "uq_user_credentials_active_password",
        "user_credentials",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'password' AND revoked_at IS NULL"),
    )
    op.create_index(
        "uq_user_credentials_active_totp",
        "user_credentials",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'totp' AND revoked_at IS NULL"),
    )
    op.create_index(
        "uq_user_credentials_active_recovery_codes",
        "user_credentials",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'recovery_codes' AND revoked_at IS NULL"),
    )

    op.create_table(
        "verification_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("channel", pg_enum(ChallengeChannel), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("purpose", pg_enum(ChallengePurpose), nullable=False),
        sa.Column("code_hash", postgresql.BYTEA(), nullable=False),
        sa.Column(
            "attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "max_attempts",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("5"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _ts("consumed_at", nullable=True),
        _ts("invalidated_at", nullable=True),
        sa.Column("request_ip", postgresql.INET(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_verification_challenges"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_verification_challenges_user_id_users",
        ),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND max_attempts",
            name="ck_verification_challenges_attempts_within_limit",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_verification_challenges_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="ck_verification_challenges_consumed_after_creation",
        ),
    )
    op.create_index(
        "ix_verification_challenges_lookup",
        "verification_challenges",
        ["destination", "purpose", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_verification_challenges_pending",
        "verification_challenges",
        ["destination", "purpose"],
        postgresql_where=sa.text("consumed_at IS NULL"),
    )

    # --- D2: Security -------------------------------------------------------
    op.create_table(
        "user_devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint_hash", sa.Text(), nullable=False),
        sa.Column("platform", pg_enum(DevicePlatform), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("app_version", sa.Text(), nullable=True),
        sa.Column("push_token", sa.Text(), nullable=True),
        sa.Column("push_provider", pg_enum(PushProvider), nullable=True),
        _ts("push_token_updated_at", nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        _ts("trusted_at", nullable=True),
        _ts("revoked_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_user_devices"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_devices_user_id_users",
        ),
        sa.UniqueConstraint(
            "user_id", "fingerprint_hash", name="uq_user_devices_user_fingerprint"
        ),
        sa.CheckConstraint(
            "push_token IS NULL OR push_provider IS NOT NULL",
            name="ck_user_devices_push_provider_required",
        ),
    )
    op.create_index("ix_user_devices_user_id", "user_devices", ["user_id"])
    op.create_index(
        "ix_user_devices_active_user",
        "user_devices",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("auth_method", pg_enum(AuthMethod), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        _ts("last_seen_at", nullable=True),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        _ts("revoked_at", nullable=True),
        sa.Column("revoked_reason", pg_enum(SessionRevokedReason), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_sessions_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["user_devices.id"],
            ondelete="SET NULL",
            name="fk_user_sessions_device_id_user_devices",
        ),
        sa.CheckConstraint(
            "absolute_expires_at > created_at",
            name="ck_user_sessions_absolute_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_reason IS NOT NULL",
            name="ck_user_sessions_revocation_reason_present",
        ),
    )
    op.create_index(
        "ix_user_sessions_user_created",
        "user_sessions",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_user_sessions_active_user",
        "user_sessions",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", postgresql.BYTEA(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _ts("used_at", nullable=True),
        _ts("revoked_at", nullable=True),
        sa.Column("revoked_reason", pg_enum(SessionRevokedReason), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["user_sessions.id"],
            ondelete="CASCADE",
            name="fk_refresh_tokens_session_id_user_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["refresh_tokens.id"],
            ondelete="SET NULL",
            name="fk_refresh_tokens_parent_id_refresh_tokens",
        ),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        sa.CheckConstraint(
            "expires_at > issued_at", name="ck_refresh_tokens_expiry_after_issue"
        ),
        sa.CheckConstraint(
            "used_at IS NULL OR used_at >= issued_at",
            name="ck_refresh_tokens_used_after_issue",
        ),
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.create_index(
        "uq_refresh_tokens_active_session",
        "refresh_tokens",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL AND revoked_at IS NULL"),
    )

    op.create_table(
        "security_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "severity",
            pg_enum(SecuritySeverity),
            nullable=False,
            server_default=sa.text("'info'"),
        ),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_security_events"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_security_events_user_id_users",
        ),
        sa.CheckConstraint(
            "char_length(event_type) BETWEEN 3 AND 100",
            name="ck_security_events_event_type_length",
        ),
    )
    op.create_index(
        "ix_security_events_user_created",
        "security_events",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_security_events_type_created",
        "security_events",
        ["event_type", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_security_events_critical_created",
        "security_events",
        ["created_at"],
        postgresql_where=sa.text("severity = 'critical'"),
    )

    op.create_table(
        "user_security_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "two_factor_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "login_alerts_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("session_idle_timeout_minutes", sa.SmallInteger(), nullable=True),
        *_audit_timestamps(),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_security_settings"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_security_settings_user_id_users",
        ),
        sa.CheckConstraint(
            "session_idle_timeout_minutes IS NULL"
            " OR session_idle_timeout_minutes BETWEEN 5 AND 43200",
            name="ck_user_security_settings_idle_timeout_range",
        ),
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.SmallInteger(), nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        _ts("expires_at", nullable=True),
        _ts("revoked_at", nullable=True),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_roles_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            ondelete="RESTRICT",
            name="fk_user_roles_role_id_roles",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_user_roles_granted_by_users",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > granted_at",
            name="ck_user_roles_expiry_after_grant",
        ),
    )
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])

    # --- D3: Profile --------------------------------------------------------
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("avatar_object_key", sa.Text(), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("country_code", sa.CHAR(2), nullable=True),
        sa.Column(
            "is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        *_audit_timestamps(),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_profiles"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_profiles_user_id_users",
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR char_length(display_name) BETWEEN 1 AND 64",
            name="ck_user_profiles_display_name_length",
        ),
        sa.CheckConstraint(
            "bio IS NULL OR char_length(bio) <= 280",
            name="ck_user_profiles_bio_length",
        ),
    )
    op.create_index(
        "ix_user_profiles_username_lower",
        "user_profiles",
        [sa.text("lower(username)")],
        unique=True,
        postgresql_where=sa.text("username IS NOT NULL"),
    )

    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "locale", sa.Text(), nullable=False, server_default=sa.text("'fa-IR'")
        ),
        sa.Column(
            "timezone",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Asia/Tehran'"),
        ),
        sa.Column(
            "theme",
            pg_enum(ThemePreference),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
        sa.Column("daily_study_goal_minutes", sa.SmallInteger(), nullable=True),
        *_audit_timestamps(),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_settings"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_settings_user_id_users",
        ),
        sa.CheckConstraint(
            "locale ~ '^[a-z]{2}(-[A-Za-z0-9]{2,8})?$'",
            name="ck_user_settings_locale_format",
        ),
        sa.CheckConstraint(
            "char_length(timezone) BETWEEN 1 AND 64",
            name="ck_user_settings_timezone_length",
        ),
        sa.CheckConstraint(
            "daily_study_goal_minutes IS NULL"
            " OR daily_study_goal_minutes BETWEEN 1 AND 600",
            name="ck_user_settings_study_goal_range",
        ),
    )

    op.create_table(
        "user_learning_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_language_id", sa.SmallInteger(), nullable=True),
        sa.Column("target_language_id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "daily_new_cards",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("10"),
        ),
        sa.Column(
            "daily_review_limit",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("200"),
        ),
        sa.Column(
            "card_modes",
            postgresql.ARRAY(pg_enum(ReviewCardMode)),
            nullable=False,
            server_default=sa.text("'{word_to_fa,fa_to_word}'::review_card_mode[]"),
        ),
        sa.Column(
            "audio_autoplay",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        *_audit_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_user_learning_settings"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_learning_settings_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["source_language_id"],
            ["languages.id"],
            ondelete="RESTRICT",
            name="fk_user_learning_settings_source_language_id_languages",
        ),
        sa.ForeignKeyConstraint(
            ["target_language_id"],
            ["languages.id"],
            ondelete="RESTRICT",
            name="fk_user_learning_settings_target_language_id_languages",
        ),
        sa.UniqueConstraint(
            "user_id", "target_language_id", name="uq_user_learning_settings_pair"
        ),
        sa.CheckConstraint(
            "daily_new_cards BETWEEN 0 AND 200",
            name="ck_user_learning_settings_daily_new_cards_range",
        ),
        sa.CheckConstraint(
            "daily_review_limit BETWEEN 0 AND 2000",
            name="ck_user_learning_settings_daily_review_limit_range",
        ),
        sa.CheckConstraint(
            "array_length(card_modes, 1) BETWEEN 1 AND 4",
            name="ck_user_learning_settings_card_modes_size",
        ),
        sa.CheckConstraint(
            "source_language_id IS NULL OR source_language_id <> target_language_id",
            name="ck_user_learning_settings_distinct_languages",
        ),
    )
    op.create_index(
        "ix_user_learning_settings_user_id", "user_learning_settings", ["user_id"]
    )
    op.create_index(
        "ix_user_learning_settings_active_pair",
        "user_learning_settings",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    # --- D4: Subscription & Billing ----------------------------------------
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.SmallInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tier", pg_enum(PlanTier), nullable=False),
        sa.Column("billing_period", pg_enum(BillingPeriod), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.CHAR(3), nullable=True),
        sa.Column(
            "trial_days", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "sort_order", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        *_audit_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_subscription_plans"),
        sa.CheckConstraint(
            "(billing_period = 'none') = (price_minor IS NULL)",
            name="ck_subscription_plans_price_matches_period",
        ),
        sa.CheckConstraint(
            "price_minor IS NULL OR price_minor >= 0",
            name="ck_subscription_plans_price_non_negative",
        ),
        sa.CheckConstraint(
            "trial_days BETWEEN 0 AND 90",
            name="ck_subscription_plans_trial_days_range",
        ),
    )
    op.create_index(
        "ix_subscription_plans_code", "subscription_plans", ["code"], unique=True
    )
    op.create_index(
        "ix_subscription_plans_active_sort",
        "subscription_plans",
        ["is_active", "sort_order"],
    )

    op.create_table(
        "plan_features",
        sa.Column("id", sa.SmallInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "value_type",
            pg_enum(FeatureValueType),
            nullable=False,
            server_default=sa.text("'boolean'"),
        ),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_features"),
        sa.CheckConstraint(
            "value_type <> 'quota' OR unit IS NOT NULL",
            name="ck_plan_features_quota_requires_unit",
        ),
    )
    op.create_index("ix_plan_features_code", "plan_features", ["code"], unique=True)

    op.create_table(
        "plan_feature_values",
        sa.Column("plan_id", sa.SmallInteger(), nullable=False),
        sa.Column("feature_id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("limit_value", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("plan_id", "feature_id", name="pk_plan_feature_values"),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["subscription_plans.id"],
            ondelete="CASCADE",
            name="fk_plan_feature_values_plan_id_subscription_plans",
        ),
        sa.ForeignKeyConstraint(
            ["feature_id"],
            ["plan_features.id"],
            ondelete="RESTRICT",
            name="fk_plan_feature_values_feature_id_plan_features",
        ),
        sa.CheckConstraint(
            "limit_value IS NULL OR limit_value >= 0",
            name="ck_plan_feature_values_limit_non_negative",
        ),
    )
    op.create_index(
        "ix_plan_feature_values_feature_id", "plan_feature_values", ["feature_id"]
    )

    op.create_table(
        "user_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "status",
            pg_enum(SubscriptionStatus),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        _ts("canceled_at", nullable=True),
        _ts("ended_at", nullable=True),
        _ts("trial_ends_at", nullable=True),
        sa.Column("provider", pg_enum(PaymentProvider), nullable=True),
        sa.Column("provider_subscription_id", sa.Text(), nullable=True),
        *_audit_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_user_subscriptions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_user_subscriptions_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["subscription_plans.id"],
            ondelete="RESTRICT",
            name="fk_user_subscriptions_plan_id_subscription_plans",
        ),
        sa.CheckConstraint(
            "current_period_end > current_period_start",
            name="ck_user_subscriptions_period_end_after_start",
        ),
        sa.CheckConstraint(
            "cancel_at_period_end = false OR canceled_at IS NOT NULL",
            name="ck_user_subscriptions_cancel_request_has_timestamp",
        ),
    )
    op.create_index(
        "ix_user_subscriptions_user_status", "user_subscriptions", ["user_id", "status"]
    )
    op.create_index(
        "ix_user_subscriptions_expiring",
        "user_subscriptions",
        ["status", "current_period_end"],
    )
    op.create_index(
        "uq_user_subscriptions_open",
        "user_subscriptions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('trialing', 'active', 'past_due')"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "status",
            pg_enum(OrderStatus),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("subtotal_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "discount_minor",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "placed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        _ts("expires_at", nullable=True),
        _ts("paid_at", nullable=True),
        _ts("canceled_at", nullable=True),
        *_audit_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_orders_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["subscription_plans.id"],
            ondelete="RESTRICT",
            name="fk_orders_plan_id_subscription_plans",
        ),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_orders_user_idempotency_key"
        ),
        sa.CheckConstraint("amount_minor >= 0", name="ck_orders_amount_non_negative"),
        sa.CheckConstraint(
            "subtotal_minor >= amount_minor",
            name="ck_orders_discount_within_subtotal",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > placed_at",
            name="ck_orders_expiry_after_placement",
        ),
    )
    op.create_index(
        "ix_orders_user_placed", "orders", ["user_id", sa.text("placed_at DESC")]
    )
    op.create_index("ix_orders_pending_expiry", "orders", ["status", "expires_at"])

    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", pg_enum(PaymentProvider), nullable=False),
        sa.Column("provider_payment_id", sa.Text(), nullable=True),
        sa.Column(
            "status",
            pg_enum(PaymentStatus),
            nullable=False,
            server_default=sa.text("'initiated'"),
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False),
        sa.Column("method", pg_enum(PaymentMethod), nullable=True),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        _ts("authorized_at", nullable=True),
        _ts("captured_at", nullable=True),
        _ts("failed_at", nullable=True),
        _ts("refunded_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            ondelete="RESTRICT",
            name="fk_payments_order_id_orders",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_payments_user_id_users",
        ),
        sa.CheckConstraint("amount_minor > 0", name="ck_payments_amount_positive"),
        sa.CheckConstraint(
            "status <> 'failed' OR failed_at IS NOT NULL",
            name="ck_payments_failed_payment_has_timestamp",
        ),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_index(
        "ix_payments_user_created", "payments", ["user_id", sa.text("created_at DESC")]
    )
    op.create_index(
        "uq_payments_provider_payment",
        "payments",
        ["provider", "provider_payment_id"],
        unique=True,
        postgresql_where=sa.text("provider_payment_id IS NOT NULL"),
    )

    op.create_table(
        "user_entitlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("feature_id", sa.SmallInteger(), nullable=False),
        sa.Column("source_type", pg_enum(EntitlementSource), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("limit_value", sa.Integer(), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        _ts("expires_at", nullable=True),
        _ts("revoked_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_user_entitlements"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_entitlements_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["feature_id"],
            ["plan_features.id"],
            ondelete="RESTRICT",
            name="fk_user_entitlements_feature_id_plan_features",
        ),
        sa.CheckConstraint(
            "limit_value IS NULL OR limit_value >= 0",
            name="ck_user_entitlements_limit_non_negative",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > granted_at",
            name="ck_user_entitlements_expiry_after_grant",
        ),
    )
    op.create_index(
        "ix_user_entitlements_user_feature",
        "user_entitlements",
        ["user_id", "feature_id"],
    )
    op.create_index(
        "ix_user_entitlements_active_user",
        "user_entitlements",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "uq_user_entitlements_source",
        "user_entitlements",
        ["user_id", "feature_id", "source_type", "source_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    # --- D5: Learning & Vocabulary ----------------------------------------
    op.create_table(
        "vocabulary",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_language_id", sa.SmallInteger(), nullable=False),
        sa.Column("lemma", sa.Text(), nullable=False),
        sa.Column("normalized_lemma", sa.Text(), nullable=False),
        sa.Column(
            "part_of_speech",
            pg_enum(PartOfSpeech),
            nullable=False,
            server_default=sa.text("'other'"),
        ),
        sa.Column("cefr_level", pg_enum(CefrLevel), nullable=True),
        sa.Column("pronunciation_ipa", sa.Text(), nullable=True),
        sa.Column("audio_object_key", sa.Text(), nullable=True),
        sa.Column("frequency_rank", sa.Integer(), nullable=True),
        sa.Column("definition_text", sa.Text(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        *_audit_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_vocabulary"),
        sa.ForeignKeyConstraint(
            ["target_language_id"],
            ["languages.id"],
            ondelete="RESTRICT",
            name="fk_vocabulary_target_language_id_languages",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_vocabulary_owner_user_id_users",
        ),
        sa.CheckConstraint(
            "char_length(lemma) BETWEEN 1 AND 120", name="ck_vocabulary_lemma_length"
        ),
        sa.CheckConstraint(
            "frequency_rank IS NULL OR frequency_rank > 0",
            name="ck_vocabulary_frequency_rank_positive",
        ),
    )
    op.create_index(
        "uq_vocabulary_public_lemma",
        "vocabulary",
        ["target_language_id", "normalized_lemma", "part_of_speech"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NULL"),
    )
    op.create_index(
        "uq_vocabulary_owner_lemma",
        "vocabulary",
        ["owner_user_id", "target_language_id", "normalized_lemma", "part_of_speech"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_vocabulary_lemma_prefix",
        "vocabulary",
        ["target_language_id", "normalized_lemma"],
        postgresql_ops={"normalized_lemma": "text_pattern_ops"},
    )
    op.create_index("ix_vocabulary_owner_user_id", "vocabulary", ["owner_user_id"])

    op.create_table(
        "vocabulary_translations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("vocabulary_id", sa.Uuid(), nullable=False),
        sa.Column("language_id", sa.SmallInteger(), nullable=False),
        sa.Column("translation", sa.Text(), nullable=False),
        sa.Column("normalized_translation", sa.Text(), nullable=False),
        sa.Column(
            "sense_index",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vocabulary_translations"),
        sa.ForeignKeyConstraint(
            ["vocabulary_id"],
            ["vocabulary.id"],
            ondelete="CASCADE",
            name="fk_vocabulary_translations_vocabulary_id_vocabulary",
        ),
        sa.ForeignKeyConstraint(
            ["language_id"],
            ["languages.id"],
            ondelete="RESTRICT",
            name="fk_vocabulary_translations_language_id_languages",
        ),
        sa.UniqueConstraint(
            "vocabulary_id",
            "language_id",
            "sense_index",
            name="uq_vocabulary_translations_sense",
        ),
        sa.UniqueConstraint(
            "vocabulary_id",
            "language_id",
            "normalized_translation",
            name="uq_vocabulary_translations_text",
        ),
        sa.CheckConstraint(
            "sense_index >= 1",
            name="ck_vocabulary_translations_sense_index_positive",
        ),
        sa.CheckConstraint(
            "char_length(translation) BETWEEN 1 AND 400",
            name="ck_vocabulary_translations_translation_length",
        ),
    )
    op.create_index(
        "ix_vocabulary_translations_vocabulary_id",
        "vocabulary_translations",
        ["vocabulary_id"],
    )

    op.create_table(
        "vocabulary_examples",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("vocabulary_id", sa.Uuid(), nullable=False),
        sa.Column("language_id", sa.SmallInteger(), nullable=False),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column("translation", sa.Text(), nullable=True),
        sa.Column("translation_language_id", sa.SmallInteger(), nullable=True),
        sa.Column(
            "source",
            pg_enum(ExampleSource),
            nullable=False,
            server_default=sa.text("'curated'"),
        ),
        sa.Column(
            "position", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("audio_object_key", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vocabulary_examples"),
        sa.ForeignKeyConstraint(
            ["vocabulary_id"],
            ["vocabulary.id"],
            ondelete="CASCADE",
            name="fk_vocabulary_examples_vocabulary_id_vocabulary",
        ),
        sa.ForeignKeyConstraint(
            ["language_id"],
            ["languages.id"],
            ondelete="RESTRICT",
            name="fk_vocabulary_examples_language_id_languages",
        ),
        sa.ForeignKeyConstraint(
            ["translation_language_id"],
            ["languages.id"],
            ondelete="RESTRICT",
            name="fk_vocabulary_examples_translation_language_id_languages",
        ),
        sa.CheckConstraint(
            "char_length(sentence) BETWEEN 1 AND 500",
            name="ck_vocabulary_examples_sentence_length",
        ),
        sa.CheckConstraint(
            "position >= 0", name="ck_vocabulary_examples_position_non_negative"
        ),
    )
    op.create_index(
        "uq_vocabulary_examples_sentence",
        "vocabulary_examples",
        ["vocabulary_id", sa.text("md5(sentence)")],
        unique=True,
    )
    op.create_index(
        "ix_vocabulary_examples_vocabulary_id", "vocabulary_examples", ["vocabulary_id"]
    )

    op.create_table(
        "learning_decks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("target_language_id", sa.SmallInteger(), nullable=False),
        sa.Column("source_language_id", sa.SmallInteger(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "visibility",
            pg_enum(DeckVisibility),
            nullable=False,
            server_default=sa.text("'private'"),
        ),
        sa.Column(
            "is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("cover_object_key", sa.Text(), nullable=True),
        *_audit_timestamps(),
        _ts("deleted_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_learning_decks"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_learning_decks_owner_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["target_language_id"],
            ["languages.id"],
            ondelete="RESTRICT",
            name="fk_learning_decks_target_language_id_languages",
        ),
        sa.ForeignKeyConstraint(
            ["source_language_id"],
            ["languages.id"],
            ondelete="RESTRICT",
            name="fk_learning_decks_source_language_id_languages",
        ),
        sa.CheckConstraint(
            "NOT is_system OR owner_user_id IS NULL",
            name="ck_learning_decks_system_deck_has_no_owner",
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 120",
            name="ck_learning_decks_title_length",
        ),
    )
    op.create_index(
        "ix_learning_decks_owner_user_id", "learning_decks", ["owner_user_id"]
    )
    op.create_index(
        "ix_learning_decks_language_visibility",
        "learning_decks",
        ["target_language_id", "visibility"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_learning_decks_owner_title",
        "learning_decks",
        ["owner_user_id", sa.text("lower(title)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND owner_user_id IS NOT NULL"),
    )

    op.create_table(
        "deck_vocabulary",
        sa.Column("deck_id", sa.Uuid(), nullable=False),
        sa.Column("vocabulary_id", sa.Uuid(), nullable=False),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.PrimaryKeyConstraint("deck_id", "vocabulary_id", name="pk_deck_vocabulary"),
        sa.ForeignKeyConstraint(
            ["deck_id"],
            ["learning_decks.id"],
            ondelete="CASCADE",
            name="fk_deck_vocabulary_deck_id_learning_decks",
        ),
        sa.ForeignKeyConstraint(
            ["vocabulary_id"],
            ["vocabulary.id"],
            ondelete="CASCADE",
            name="fk_deck_vocabulary_vocabulary_id_vocabulary",
        ),
        sa.CheckConstraint(
            "position >= 0", name="ck_deck_vocabulary_position_non_negative"
        ),
    )
    op.create_index(
        "ix_deck_vocabulary_vocabulary_id", "deck_vocabulary", ["vocabulary_id"]
    )

    op.create_table(
        "user_vocabulary",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("vocabulary_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            pg_enum(UserVocabularyStatus),
            nullable=False,
            server_default=sa.text("'learning'"),
        ),
        sa.Column(
            "source",
            pg_enum(UserVocabularySource),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        _ts("last_interacted_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_user_vocabulary"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_vocabulary_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["vocabulary_id"],
            ["vocabulary.id"],
            ondelete="RESTRICT",
            name="fk_user_vocabulary_vocabulary_id_vocabulary",
        ),
        sa.UniqueConstraint(
            "user_id", "vocabulary_id", name="uq_user_vocabulary_user_word"
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_user_vocabulary_id_user"),
    )
    op.create_index(
        "ix_user_vocabulary_user_status", "user_vocabulary", ["user_id", "status"]
    )
    op.create_index(
        "ix_user_vocabulary_vocabulary_id", "user_vocabulary", ["vocabulary_id"]
    )

    # --- D6: Review & FSRS --------------------------------------------------
    op.create_table(
        "fsrs_parameters",
        sa.Column("id", sa.SmallInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("algorithm_version", sa.Text(), nullable=False),
        sa.Column(
            "weights", postgresql.ARRAY(postgresql.DOUBLE_PRECISION()), nullable=False
        ),
        sa.Column(
            "is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "source",
            pg_enum(FsrsParameterSource),
            nullable=False,
            server_default=sa.text("'default'"),
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fsrs_parameters"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_fsrs_parameters_created_by_user_id_users",
        ),
        sa.CheckConstraint(
            "array_length(weights, 1) BETWEEN 1 AND 64",
            name="ck_fsrs_parameters_weights_size",
        ),
    )
    op.create_index(
        "uq_fsrs_parameters_default_version",
        "fsrs_parameters",
        ["algorithm_version"],
        unique=True,
        postgresql_where=sa.text("is_default AND created_by_user_id IS NULL"),
    )
    op.create_index(
        "ix_fsrs_parameters_created_by_user_id",
        "fsrs_parameters",
        ["created_by_user_id"],
    )

    op.create_table(
        "review_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("user_vocabulary_id", sa.Uuid(), nullable=False),
        sa.Column("mode", pg_enum(ReviewCardMode), nullable=False),
        sa.Column(
            "is_suspended",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        _ts("suspended_at", nullable=True),
        *_audit_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_review_cards"),
        sa.ForeignKeyConstraint(
            ["user_vocabulary_id", "user_id"],
            ["user_vocabulary.id", "user_vocabulary.user_id"],
            ondelete="CASCADE",
            name="fk_review_cards_user_vocabulary",
        ),
        sa.UniqueConstraint(
            "user_vocabulary_id", "mode", name="uq_review_cards_vocabulary_mode"
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_review_cards_id_user"),
        sa.CheckConstraint(
            "is_suspended = (suspended_at IS NOT NULL)",
            name="ck_review_cards_suspension_flag_matches_timestamp",
        ),
    )
    op.create_index(
        "ix_review_cards_active_user",
        "review_cards",
        ["user_id"],
        postgresql_where=sa.text("NOT is_suspended"),
    )
    op.create_index(
        "ix_review_cards_user_vocabulary_id", "review_cards", ["user_vocabulary_id"]
    )

    op.create_table(
        "fsrs_card_states",
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "state",
            pg_enum(FsrsState),
            nullable=False,
            server_default=sa.text("'new'"),
        ),
        sa.Column(
            "due_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column(
            "stability",
            postgresql.DOUBLE_PRECISION(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "difficulty",
            postgresql.DOUBLE_PRECISION(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("reps", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("lapses", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "learning_step",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "elapsed_days", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "scheduled_days", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        _ts("last_reviewed_at", nullable=True),
        sa.Column("parameters_id", sa.SmallInteger(), nullable=True),
        sa.Column(
            "algorithm_version",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'FSRS-5'"),
        ),
        sa.Column(
            "row_version", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        *_audit_timestamps(),
        sa.PrimaryKeyConstraint("card_id", name="pk_fsrs_card_states"),
        sa.ForeignKeyConstraint(
            ["card_id", "user_id"],
            ["review_cards.id", "review_cards.user_id"],
            ondelete="CASCADE",
            name="fk_fsrs_card_states_card_owner",
        ),
        sa.ForeignKeyConstraint(
            ["parameters_id"],
            ["fsrs_parameters.id"],
            ondelete="RESTRICT",
            name="fk_fsrs_card_states_parameters_id_fsrs_parameters",
        ),
        sa.CheckConstraint(
            "stability >= 0", name="ck_fsrs_card_states_stability_non_negative"
        ),
        sa.CheckConstraint(
            "difficulty BETWEEN 0 AND 10", name="ck_fsrs_card_states_difficulty_range"
        ),
        sa.CheckConstraint("reps >= 0", name="ck_fsrs_card_states_reps_non_negative"),
        sa.CheckConstraint(
            "lapses >= 0", name="ck_fsrs_card_states_lapses_non_negative"
        ),
        sa.CheckConstraint(
            "row_version >= 0", name="ck_fsrs_card_states_row_version_non_negative"
        ),
        sa.CheckConstraint(
            "learning_step >= 0",
            name="ck_fsrs_card_states_learning_step_non_negative",
        ),
    )
    op.create_index(
        "ix_fsrs_card_states_due", "fsrs_card_states", ["user_id", "due_at"]
    )
    op.create_index(
        "ix_fsrs_card_states_parameters_id", "fsrs_card_states", ["parameters_id"]
    )

    op.create_table(
        "fsrs_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "desired_retention",
            sa.Numeric(4, 3),
            nullable=False,
            server_default=sa.text("0.900"),
        ),
        sa.Column(
            "maximum_interval_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("36500"),
        ),
        sa.Column(
            "enable_fuzz", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "learning_steps",
            postgresql.ARRAY(sa.SmallInteger()),
            nullable=False,
            server_default=sa.text("'{1,10}'::smallint[]"),
        ),
        sa.Column(
            "relearning_steps",
            postgresql.ARRAY(sa.SmallInteger()),
            nullable=False,
            server_default=sa.text("'{10}'::smallint[]"),
        ),
        sa.Column("parameters_id", sa.SmallInteger(), nullable=True),
        *_audit_timestamps(),
        sa.PrimaryKeyConstraint("user_id", name="pk_fsrs_settings"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_fsrs_settings_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["parameters_id"],
            ["fsrs_parameters.id"],
            ondelete="RESTRICT",
            name="fk_fsrs_settings_parameters_id_fsrs_parameters",
        ),
        sa.CheckConstraint(
            "desired_retention BETWEEN 0.700 AND 0.990",
            name="ck_fsrs_settings_desired_retention_range",
        ),
        sa.CheckConstraint(
            "maximum_interval_days BETWEEN 1 AND 36500",
            name="ck_fsrs_settings_maximum_interval_range",
        ),
        sa.CheckConstraint(
            "array_length(learning_steps, 1) BETWEEN 1 AND 8",
            name="ck_fsrs_settings_learning_steps_size",
        ),
        sa.CheckConstraint(
            "array_length(relearning_steps, 1) BETWEEN 1 AND 8",
            name="ck_fsrs_settings_relearning_steps_size",
        ),
    )

    op.create_table(
        "review_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=True),
        sa.Column("user_vocabulary_id", sa.Uuid(), nullable=True),
        sa.Column("vocabulary_id", sa.Uuid(), nullable=True),
        sa.Column("card_mode", pg_enum(ReviewCardMode), nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("reviewed_on", sa.Date(), nullable=False),
        sa.Column("state_before", pg_enum(FsrsState), nullable=False),
        sa.Column("state_after", pg_enum(FsrsState), nullable=False),
        _ts("due_before", nullable=True),
        _ts("due_after", nullable=True),
        sa.Column("stability_before", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("stability_after", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("difficulty_before", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("difficulty_after", postgresql.DOUBLE_PRECISION(), nullable=True),
        sa.Column("elapsed_days", sa.Integer(), nullable=True),
        sa.Column("scheduled_days", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("algorithm_version", sa.Text(), nullable=False),
        sa.Column("parameters_id", sa.SmallInteger(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_history"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_review_history_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["review_cards.id"],
            ondelete="SET NULL",
            name="fk_review_history_card_id_review_cards",
        ),
        sa.ForeignKeyConstraint(
            ["user_vocabulary_id"],
            ["user_vocabulary.id"],
            ondelete="SET NULL",
            name="fk_review_history_user_vocabulary_id_user_vocabulary",
        ),
        sa.ForeignKeyConstraint(
            ["vocabulary_id"],
            ["vocabulary.id"],
            ondelete="SET NULL",
            name="fk_review_history_vocabulary_id_vocabulary",
        ),
        sa.ForeignKeyConstraint(
            ["parameters_id"],
            ["fsrs_parameters.id"],
            ondelete="RESTRICT",
            name="fk_review_history_parameters_id_fsrs_parameters",
        ),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_review_history_idempotency"
        ),
        sa.CheckConstraint(
            "rating BETWEEN 1 AND 4", name="ck_review_history_rating_range"
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms BETWEEN 0 AND 600000",
            name="ck_review_history_duration_ms_range",
        ),
    )
    op.create_index(
        "ix_review_history_user_reviewed",
        "review_history",
        ["user_id", sa.text("reviewed_at DESC")],
    )
    op.create_index(
        "ix_review_history_card_reviewed",
        "review_history",
        ["card_id", sa.text("reviewed_at DESC")],
    )
    op.create_index(
        "ix_review_history_user_day", "review_history", ["user_id", "reviewed_on"]
    )
    op.create_index(
        "ix_review_history_vocabulary_id", "review_history", ["vocabulary_id"]
    )

    # --- D7: Notification ---------------------------------------------------
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("quiet_hours_start", sa.Time(), nullable=True),
        sa.Column("quiet_hours_end", sa.Time(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "category", "channel", name="pk_notification_preferences"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_notification_preferences_user_id_users",
        ),
        sa.CheckConstraint(
            "category IN ('review_reminder', 'streak', 'subscription',"
            " 'product_updates', 'security')",
            name="ck_notification_preferences_category_allowed",
        ),
        sa.CheckConstraint(
            "channel IN ('push', 'email', 'sms')",
            name="ck_notification_preferences_channel_allowed",
        ),
        sa.CheckConstraint(
            "NOT (category = 'security' AND is_enabled = false)",
            name="ck_notification_preferences_security_always_enabled",
        ),
        sa.CheckConstraint(
            "(quiet_hours_start IS NULL) = (quiet_hours_end IS NULL)",
            name="ck_notification_preferences_quiet_hours_complete",
        ),
    )

    op.create_table(
        "scheduled_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("review_card_id", sa.Uuid(), nullable=True),
        sa.Column("trigger_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deliver_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column(
            "attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "max_attempts",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("5"),
        ),
        _ts("next_attempt_at", nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        *_audit_timestamps(),
        _ts("sent_at", nullable=True),
        _ts("canceled_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_scheduled_notifications"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_scheduled_notifications_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["user_devices.id"],
            ondelete="SET NULL",
            name="fk_scheduled_notifications_device_id_user_devices",
        ),
        sa.ForeignKeyConstraint(
            ["review_card_id"],
            ["review_cards.id"],
            ondelete="CASCADE",
            name="fk_scheduled_notifications_review_card_id_review_cards",
        ),
        sa.UniqueConstraint(
            "user_id", "dedupe_key", name="uq_scheduled_notifications_user_dedupe"
        ),
        sa.CheckConstraint(
            "category IN ('review_reminder', 'streak', 'subscription',"
            " 'product_updates', 'security')",
            name="ck_scheduled_notifications_category_allowed",
        ),
        sa.CheckConstraint(
            "channel IN ('push', 'email')",
            name="ck_scheduled_notifications_channel_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'queued', 'sending', 'sent', 'canceled',"
            " 'failed', 'dead')",
            name="ck_scheduled_notifications_status_allowed",
        ),
        sa.CheckConstraint(
            "attempts <= max_attempts",
            name="ck_scheduled_notifications_attempts_within_limit",
        ),
        sa.CheckConstraint(
            "status <> 'sent' OR sent_at IS NOT NULL",
            name="ck_scheduled_notifications_sent_has_timestamp",
        ),
    )
    op.create_index(
        "ix_scheduled_notifications_dispatch",
        "scheduled_notifications",
        ["status", "deliver_after"],
        postgresql_where=sa.text("status IN ('pending', 'queued')"),
    )
    op.create_index(
        "ix_scheduled_notifications_user_id", "scheduled_notifications", ["user_id"]
    )

    op.create_table(
        "notification_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_notification_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("delivery_status", sa.Text(), nullable=False),
        _ts("sent_at", nullable=True),
        _ts("delivered_at", nullable=True),
        _ts("seen_at", nullable=True),
        _ts("failed_at", nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_history"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_notification_history_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["scheduled_notification_id"],
            ["scheduled_notifications.id"],
            ondelete="SET NULL",
            # Trimmed to PostgreSQL's 63-character identifier limit.
            name="fk_notification_history_scheduled_notification",
        ),
        sa.CheckConstraint(
            "channel IN ('push', 'email', 'sms')",
            name="ck_notification_history_channel_allowed",
        ),
        sa.CheckConstraint(
            "delivery_status IN ('accepted', 'delivered', 'failed', 'bounced',"
            " 'suppressed')",
            name="ck_notification_history_delivery_status_allowed",
        ),
        sa.CheckConstraint(
            "delivery_status <> 'delivered' OR delivered_at IS NOT NULL",
            name="ck_notification_history_delivered_has_timestamp",
        ),
    )
    op.create_index(
        "ix_notification_history_user_created",
        "notification_history",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_notification_history_scheduled_notification_id",
        "notification_history",
        ["scheduled_notification_id"],
    )

    # --- D8: Platform -------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", pg_enum(ActorType), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("before_data", postgresql.JSONB(), nullable=True),
        sa.Column("after_data", postgresql.JSONB(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name="fk_audit_logs_actor_user_id_users",
        ),
        sa.CheckConstraint(
            "char_length(action) BETWEEN 3 AND 100",
            name="ck_audit_logs_action_length",
        ),
    )
    op.create_index(
        "ix_audit_logs_entity",
        "audit_logs",
        ["entity_type", "entity_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_audit_logs_actor",
        "audit_logs",
        ["actor_user_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        _ts("processed_at", nullable=True),
        sa.Column(
            "attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.CheckConstraint(
            "char_length(event_type) BETWEEN 3 AND 100",
            name="ck_outbox_events_event_type_length",
        ),
    )
    op.create_index(
        "uq_outbox_events_dedupe_key",
        "outbox_events",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["available_at", "id"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )


def downgrade() -> None:
    """Drop every table, then every enum type (reverse creation order)."""

    for table in (
        "outbox_events",
        "audit_logs",
        "notification_history",
        "scheduled_notifications",
        "notification_preferences",
        "review_history",
        "fsrs_settings",
        "fsrs_card_states",
        "review_cards",
        "fsrs_parameters",
        "user_vocabulary",
        "deck_vocabulary",
        "learning_decks",
        "vocabulary_examples",
        "vocabulary_translations",
        "vocabulary",
        "user_entitlements",
        "payments",
        "orders",
        "user_subscriptions",
        "plan_feature_values",
        "plan_features",
        "subscription_plans",
        "user_learning_settings",
        "user_settings",
        "user_profiles",
        "user_roles",
        "user_security_settings",
        "security_events",
        "refresh_tokens",
        "user_sessions",
        "user_devices",
        "verification_challenges",
        "user_credentials",
        "user_identities",
        "languages",
        "roles",
        "users",
    ):
        op.drop_table(table)

    for name in reversed(tuple(ENUM_VALUES)):
        op.execute(f"DROP TYPE IF EXISTS {name}")
