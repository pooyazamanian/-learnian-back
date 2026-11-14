"""Review domain: cards, FSRS state, the review ledger and algorithm settings.

A card is ``(user vocabulary, review direction)`` - the identity of what is
being practised. Its scheduling state lives in a separate 1:1 table because
that row is updated on every answer, and it carries the optimistic-lock
version. ``review_history`` is append-only: no update, no cascade from users.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, DOUBLE_PRECISION
from sqlalchemy.orm import Mapped, mapped_column

from lurnian.core.database import Base
from lurnian.core.enums import (
    FsrsParameterSource,
    FsrsState,
    ReviewCardMode,
    pg_enum,
)
from lurnian.core.types import TimestampMixin, new_uuid


class ReviewCard(Base, TimestampMixin):
    """Identity of a card: which enrolled word, which practice direction."""

    __tablename__ = "review_cards"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_vocabulary_id", "user_id"],
            ["user_vocabulary.id", "user_vocabulary.user_id"],
            ondelete="CASCADE",
            name="fk_review_cards_user_vocabulary",
        ),
        UniqueConstraint(
            "user_vocabulary_id", "mode", name="uq_review_cards_vocabulary_mode"
        ),
        # Target of the composite foreign keys from state and history.
        UniqueConstraint("id", "user_id", name="uq_review_cards_id_user"),
        CheckConstraint(
            "is_suspended = (suspended_at IS NOT NULL)",
            name="suspension_flag_matches_timestamp",
        ),
        Index(
            "ix_review_cards_active_user",
            "user_id",
            postgresql_where=text("NOT is_suspended"),
        ),
        Index("ix_review_cards_user_vocabulary_id", "user_vocabulary_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_vocabulary_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    mode: Mapped[ReviewCardMode] = mapped_column(
        pg_enum(ReviewCardMode), nullable=False
    )
    is_suspended: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FsrsCardState(Base, TimestampMixin):
    """FSRS scheduling state of one card. Updated on every answer."""

    __tablename__ = "fsrs_card_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["card_id", "user_id"],
            ["review_cards.id", "review_cards.user_id"],
            ondelete="CASCADE",
            name="fk_fsrs_card_states_card_owner",
        ),
        CheckConstraint("stability >= 0", name="stability_non_negative"),
        # 0 means "never rated yet"; the FSRS range itself is 1..10.
        CheckConstraint("difficulty BETWEEN 0 AND 10", name="difficulty_range"),
        CheckConstraint("reps >= 0", name="reps_non_negative"),
        CheckConstraint("lapses >= 0", name="lapses_non_negative"),
        CheckConstraint("row_version >= 0", name="row_version_non_negative"),
        CheckConstraint("learning_step >= 0", name="learning_step_non_negative"),
        Index("ix_fsrs_card_states_due", "user_id", "due_at"),
        Index("ix_fsrs_card_states_parameters_id", "parameters_id"),
    )

    card_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    state: Mapped[FsrsState] = mapped_column(
        pg_enum(FsrsState), nullable=False, server_default=text("'new'")
    )
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    stability: Mapped[float] = mapped_column(
        DOUBLE_PRECISION, nullable=False, server_default=text("0")
    )
    difficulty: Mapped[float] = mapped_column(
        DOUBLE_PRECISION, nullable=False, server_default=text("0")
    )
    reps: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lapses: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    learning_step: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    elapsed_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    scheduled_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parameters_id: Mapped[int | None] = mapped_column(
        ForeignKey("fsrs_parameters.id", ondelete="RESTRICT")
    )
    algorithm_version: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'FSRS-5'")
    )
    # Optimistic concurrency: answers update "WHERE row_version = :expected".
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )


class ReviewHistory(Base):
    """Append-only ledger: every answer with a full before/after snapshot.

    No ``updated_at`` and no update path. ``card_id`` is nullable so deleting a
    card cannot erase what the user actually did.
    """

    __tablename__ = "review_history"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 4", name="rating_range"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms BETWEEN 0 AND 600000",
            name="duration_ms_range",
        ),
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_review_history_idempotency"
        ),
        Index(
            "ix_review_history_user_reviewed",
            "user_id",
            text("reviewed_at DESC"),
        ),
        Index("ix_review_history_card_reviewed", "card_id", text("reviewed_at DESC")),
        Index("ix_review_history_user_day", "user_id", "reviewed_on"),
        Index("ix_review_history_vocabulary_id", "vocabulary_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    card_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("review_cards.id", ondelete="SET NULL")
    )
    user_vocabulary_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_vocabulary.id", ondelete="SET NULL")
    )
    vocabulary_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vocabulary.id", ondelete="SET NULL")
    )
    card_mode: Mapped[ReviewCardMode | None] = mapped_column(pg_enum(ReviewCardMode))
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Calendar day in the user's timezone: basis for daily caps and streaks.
    reviewed_on: Mapped[date] = mapped_column(Date, nullable=False)
    state_before: Mapped[FsrsState] = mapped_column(pg_enum(FsrsState), nullable=False)
    state_after: Mapped[FsrsState] = mapped_column(pg_enum(FsrsState), nullable=False)
    due_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stability_before: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    stability_after: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    difficulty_before: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    difficulty_after: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    elapsed_days: Mapped[int | None] = mapped_column(Integer)
    scheduled_days: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    algorithm_version: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_id: Mapped[int | None] = mapped_column(
        ForeignKey("fsrs_parameters.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FsrsSettings(Base, TimestampMixin):
    """Scheduling policy of one user: retention target, interval cap, steps."""

    __tablename__ = "fsrs_settings"
    __table_args__ = (
        CheckConstraint(
            "desired_retention BETWEEN 0.700 AND 0.990",
            name="desired_retention_range",
        ),
        CheckConstraint(
            "maximum_interval_days BETWEEN 1 AND 36500",
            name="maximum_interval_range",
        ),
        CheckConstraint(
            "array_length(learning_steps, 1) BETWEEN 1 AND 8",
            name="learning_steps_size",
        ),
        CheckConstraint(
            "array_length(relearning_steps, 1) BETWEEN 1 AND 8",
            name="relearning_steps_size",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    desired_retention: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, server_default=text("0.900")
    )
    maximum_interval_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("36500")
    )
    enable_fuzz: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("true")
    )
    learning_steps: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger),
        nullable=False,
        server_default=text("'{1,10}'::smallint[]"),
    )
    relearning_steps: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger),
        nullable=False,
        server_default=text("'{10}'::smallint[]"),
    )
    parameters_id: Mapped[int | None] = mapped_column(
        ForeignKey("fsrs_parameters.id", ondelete="RESTRICT")
    )


class FsrsParameters(Base):
    """Catalog of algorithm weights per version, so results stay reproducible.

    Without this table a weight change would rewrite history: every review row
    and card state stores the parameter set it was computed with.
    """

    __tablename__ = "fsrs_parameters"
    __table_args__ = (
        CheckConstraint(
            "array_length(weights, 1) BETWEEN 1 AND 64", name="weights_size"
        ),
        Index(
            "uq_fsrs_parameters_default_version",
            "algorithm_version",
            unique=True,
            postgresql_where=text("is_default AND created_by_user_id IS NULL"),
        ),
        Index("ix_fsrs_parameters_created_by_user_id", "created_by_user_id"),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, Identity(always=False), primary_key=True
    )
    algorithm_version: Mapped[str] = mapped_column(Text, nullable=False)
    # Native array: always a homogeneous numeric vector, never queried by key.
    weights: Mapped[list[float]] = mapped_column(
        ARRAY(DOUBLE_PRECISION), nullable=False
    )
    is_default: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    source: Mapped[FsrsParameterSource] = mapped_column(
        pg_enum(FsrsParameterSource), nullable=False, server_default=text("'default'")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
