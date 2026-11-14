"""Profile domain: public profile data, app settings and learning settings.

Display settings ("how the app looks") and learning settings ("what is
studied") live in separate tables so their write paths never contend.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from lurnian.core.database import Base
from lurnian.core.enums import ReviewCardMode, ThemePreference, pg_enum
from lurnian.core.types import TimestampMixin, new_uuid


class UserProfile(Base, TimestampMixin):
    """Publicly visible profile fields; never a place for email or phone."""

    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint(
            "display_name IS NULL OR char_length(display_name) BETWEEN 1 AND 64",
            name="display_name_length",
        ),
        CheckConstraint("bio IS NULL OR char_length(bio) <= 280", name="bio_length"),
        Index(
            "ix_user_profiles_username_lower",
            func.lower(text("username")),
            unique=True,
            postgresql_where=text("username IS NOT NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    username: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    avatar_object_key: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(CHAR(2))
    is_public: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )


class UserSettings(Base, TimestampMixin):
    """Display and locale settings; the timezone drives ``reviewed_on``."""

    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint(
            "locale ~ '^[a-z]{2}(-[A-Za-z0-9]{2,8})?$'", name="locale_format"
        ),
        CheckConstraint(
            "char_length(timezone) BETWEEN 1 AND 64", name="timezone_length"
        ),
        CheckConstraint(
            "daily_study_goal_minutes IS NULL"
            " OR daily_study_goal_minutes BETWEEN 1 AND 600",
            name="study_goal_range",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'fa-IR'")
    )
    timezone: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Asia/Tehran'")
    )
    theme: Mapped[ThemePreference] = mapped_column(
        pg_enum(ThemePreference), nullable=False, server_default=text("'system'")
    )
    daily_study_goal_minutes: Mapped[int | None] = mapped_column(SmallInteger)


class UserLearningSettings(Base, TimestampMixin):
    """Active language pair, daily caps and the review directions in use.

    Daily caps are *defined* here but *enforced* by the Review domain, which
    counts consumption in ``review_history`` instead of writing back here.
    """

    __tablename__ = "user_learning_settings"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "target_language_id", name="uq_user_learning_settings_pair"
        ),
        CheckConstraint(
            "daily_new_cards BETWEEN 0 AND 200", name="daily_new_cards_range"
        ),
        CheckConstraint(
            "daily_review_limit BETWEEN 0 AND 2000", name="daily_review_limit_range"
        ),
        CheckConstraint(
            "array_length(card_modes, 1) BETWEEN 1 AND 4", name="card_modes_size"
        ),
        CheckConstraint(
            "source_language_id IS NULL OR source_language_id <> target_language_id",
            name="distinct_languages",
        ),
        Index("ix_user_learning_settings_user_id", "user_id"),
        Index(
            "ix_user_learning_settings_active_pair",
            "user_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_language_id: Mapped[int | None] = mapped_column(
        ForeignKey("languages.id", ondelete="RESTRICT")
    )
    target_language_id: Mapped[int] = mapped_column(
        ForeignKey("languages.id", ondelete="RESTRICT"), nullable=False
    )
    daily_new_cards: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("10")
    )
    daily_review_limit: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("200")
    )
    # Four values from a closed enum do not justify a join table.
    card_modes: Mapped[list[ReviewCardMode]] = mapped_column(
        ARRAY(pg_enum(ReviewCardMode)),
        nullable=False,
        server_default=text("'{word_to_fa,fa_to_word}'::review_card_mode[]"),
    )
    audio_autoplay: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("true")
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
