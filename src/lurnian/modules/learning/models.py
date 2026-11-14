"""Learning domain: languages, vocabulary content, decks and enrollment.

Content and progress are separated: ``vocabulary`` never holds per-user state,
and ``user_vocabulary`` is the only gate through which a word enters a user's
study plan (and therefore the only source of review cards).
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
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from lurnian.core.database import Base
from lurnian.core.enums import (
    CefrLevel,
    DeckVisibility,
    ExampleSource,
    PartOfSpeech,
    TextDirection,
    UserVocabularySource,
    UserVocabularyStatus,
    pg_enum,
)
from lurnian.core.types import TimestampMixin, new_uuid


class Language(Base):
    """Catalog of languages, used as both source and target."""

    __tablename__ = "languages"
    __table_args__ = (
        Index("ix_languages_code", "code", unique=True),
        Index("ix_languages_bcp47", "bcp47", unique=True),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, Identity(always=False), primary_key=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    bcp47: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_native: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[TextDirection] = mapped_column(
        pg_enum(TextDirection), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )


class Vocabulary(Base, TimestampMixin):
    """One word in one language: shared catalog row or a user's private word.

    Public and private uniqueness are separate partial indexes, so a user may
    keep a private variant of a catalog word without duplicating the catalog.
    """

    __tablename__ = "vocabulary"
    __table_args__ = (
        CheckConstraint("char_length(lemma) BETWEEN 1 AND 120", name="lemma_length"),
        CheckConstraint(
            "frequency_rank IS NULL OR frequency_rank > 0",
            name="frequency_rank_positive",
        ),
        Index(
            "uq_vocabulary_public_lemma",
            "target_language_id",
            "normalized_lemma",
            "part_of_speech",
            unique=True,
            postgresql_where=text("owner_user_id IS NULL"),
        ),
        Index(
            "uq_vocabulary_owner_lemma",
            "owner_user_id",
            "target_language_id",
            "normalized_lemma",
            "part_of_speech",
            unique=True,
            postgresql_where=text("owner_user_id IS NOT NULL"),
        ),
        Index(
            "ix_vocabulary_lemma_prefix",
            "target_language_id",
            "normalized_lemma",
            postgresql_ops={"normalized_lemma": "text_pattern_ops"},
        ),
        Index("ix_vocabulary_owner_user_id", "owner_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    target_language_id: Mapped[int] = mapped_column(
        ForeignKey("languages.id", ondelete="RESTRICT"), nullable=False
    )
    lemma: Mapped[str] = mapped_column(Text, nullable=False)
    # Computed by the application (lowercase, diacritics removed).
    normalized_lemma: Mapped[str] = mapped_column(Text, nullable=False)
    part_of_speech: Mapped[PartOfSpeech] = mapped_column(
        pg_enum(PartOfSpeech), nullable=False, server_default=text("'other'")
    )
    cefr_level: Mapped[CefrLevel | None] = mapped_column(pg_enum(CefrLevel))
    pronunciation_ipa: Mapped[str | None] = mapped_column(Text)
    audio_object_key: Mapped[str | None] = mapped_column(Text)
    frequency_rank: Mapped[int | None] = mapped_column(Integer)
    definition_text: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))


class VocabularyTranslation(Base):
    """Meaning of a word in a display language; the source of meaning prompts."""

    __tablename__ = "vocabulary_translations"
    __table_args__ = (
        UniqueConstraint(
            "vocabulary_id",
            "language_id",
            "sense_index",
            name="uq_vocabulary_translations_sense",
        ),
        UniqueConstraint(
            "vocabulary_id",
            "language_id",
            "normalized_translation",
            name="uq_vocabulary_translations_text",
        ),
        CheckConstraint("sense_index >= 1", name="sense_index_positive"),
        CheckConstraint(
            "char_length(translation) BETWEEN 1 AND 400", name="translation_length"
        ),
        Index("ix_vocabulary_translations_vocabulary_id", "vocabulary_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), primary_key=True
    )
    vocabulary_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vocabulary.id", ondelete="CASCADE"), nullable=False
    )
    language_id: Mapped[int] = mapped_column(
        ForeignKey("languages.id", ondelete="RESTRICT"), nullable=False
    )
    translation: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_translation: Mapped[str] = mapped_column(Text, nullable=False)
    sense_index: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VocabularyExample(Base):
    """Example sentence for a word, with an optional translation."""

    __tablename__ = "vocabulary_examples"
    __table_args__ = (
        CheckConstraint(
            "char_length(sentence) BETWEEN 1 AND 500", name="sentence_length"
        ),
        CheckConstraint("position >= 0", name="position_non_negative"),
        Index(
            "uq_vocabulary_examples_sentence",
            "vocabulary_id",
            func.md5(text("sentence")),
            unique=True,
        ),
        Index("ix_vocabulary_examples_vocabulary_id", "vocabulary_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), primary_key=True
    )
    vocabulary_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vocabulary.id", ondelete="CASCADE"), nullable=False
    )
    language_id: Mapped[int] = mapped_column(
        ForeignKey("languages.id", ondelete="RESTRICT"), nullable=False
    )
    sentence: Mapped[str] = mapped_column(Text, nullable=False)
    translation: Mapped[str | None] = mapped_column(Text)
    translation_language_id: Mapped[int | None] = mapped_column(
        ForeignKey("languages.id", ondelete="RESTRICT")
    )
    source: Mapped[ExampleSource] = mapped_column(
        pg_enum(ExampleSource), nullable=False, server_default=text("'curated'")
    )
    position: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    audio_object_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LearningDeck(Base, TimestampMixin):
    """Container of words (official or personal). Holds no learning state."""

    __tablename__ = "learning_decks"
    __table_args__ = (
        CheckConstraint(
            "NOT is_system OR owner_user_id IS NULL", name="system_deck_has_no_owner"
        ),
        CheckConstraint("char_length(title) BETWEEN 1 AND 120", name="title_length"),
        Index("ix_learning_decks_owner_user_id", "owner_user_id"),
        Index(
            "ix_learning_decks_language_visibility",
            "target_language_id",
            "visibility",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_learning_decks_owner_title",
            "owner_user_id",
            func.lower(text("title")),
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND owner_user_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    target_language_id: Mapped[int] = mapped_column(
        ForeignKey("languages.id", ondelete="RESTRICT"), nullable=False
    )
    source_language_id: Mapped[int | None] = mapped_column(
        ForeignKey("languages.id", ondelete="RESTRICT")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[DeckVisibility] = mapped_column(
        pg_enum(DeckVisibility), nullable=False, server_default=text("'private'")
    )
    is_system: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    cover_object_key: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeckVocabulary(Base):
    """Membership of a word in a deck, with manual ordering."""

    __tablename__ = "deck_vocabulary"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position_non_negative"),
        Index("ix_deck_vocabulary_vocabulary_id", "vocabulary_id"),
    )

    deck_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("learning_decks.id", ondelete="CASCADE"), primary_key=True
    )
    vocabulary_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vocabulary.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserVocabulary(Base):
    """A word enrolled in one user's study plan.

    ``UNIQUE (id, user_id)`` looks redundant next to the primary key, but it is
    the target of the composite foreign key from ``review_cards``; that is what
    makes a card pointing at another user's word impossible in the database.
    """

    __tablename__ = "user_vocabulary"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "vocabulary_id", name="uq_user_vocabulary_user_word"
        ),
        UniqueConstraint("id", "user_id", name="uq_user_vocabulary_id_user"),
        Index("ix_user_vocabulary_user_status", "user_id", "status"),
        Index("ix_user_vocabulary_vocabulary_id", "vocabulary_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    vocabulary_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vocabulary.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[UserVocabularyStatus] = mapped_column(
        pg_enum(UserVocabularyStatus),
        nullable=False,
        server_default=text("'learning'"),
    )
    source: Mapped[UserVocabularySource] = mapped_column(
        pg_enum(UserVocabularySource),
        nullable=False,
        server_default=text("'manual'"),
    )
    notes: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_interacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
