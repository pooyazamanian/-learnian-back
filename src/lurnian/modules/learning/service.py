"""Read-only learning queries consumed by other domains.

Review needs a language pair, the enabled directions and the daily caps, plus
the words and prompt material behind the cards it serves. It gets them through
this interface instead of querying Learning tables directly.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lurnian.core.enums import ReviewCardMode
from lurnian.core.exceptions import NotFoundError
from lurnian.modules.learning.models import (
    Language,
    UserVocabulary,
    Vocabulary,
    VocabularyTranslation,
)
from lurnian.modules.profile.models import UserLearningSettings


@dataclass(frozen=True, slots=True)
class StudySettings:
    """The pair and limits that shape one user's review queue."""

    target_language_id: int
    source_language_id: int | None
    card_modes: tuple[ReviewCardMode, ...]
    daily_new_cards: int
    daily_review_limit: int


@dataclass(frozen=True, slots=True)
class EnrolledWord:
    """The content Review needs for one enrolled word."""

    vocabulary_id: uuid.UUID
    lemma: str
    definition_text: str | None


class LearningQuery:
    """Read side of the Learning domain, safe for cross-domain use."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def study_settings(self, user_id: uuid.UUID) -> StudySettings:
        """Return the active language pair, or explain why there is none."""
        row = await self._session.scalar(
            select(UserLearningSettings).where(
                UserLearningSettings.user_id == user_id,
                UserLearningSettings.is_active.is_(True),
            )
        )
        if row is None:
            raise NotFoundError(
                "No active learning settings; choose a language pair first"
            )
        return StudySettings(
            target_language_id=row.target_language_id,
            source_language_id=row.source_language_id,
            card_modes=tuple(row.card_modes),
            daily_new_cards=row.daily_new_cards,
            daily_review_limit=row.daily_review_limit,
        )

    async def enrolled_words(
        self, *, user_id: uuid.UUID, user_vocabulary_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, EnrolledWord]:
        """Return ``{user_vocabulary_id: word}`` in one batched query.

        Retired words are omitted: nothing should enter a queue for a word the
        catalog has retired.
        """
        if not user_vocabulary_ids:
            return {}
        statement = (
            select(
                UserVocabulary.id,
                Vocabulary.id,
                Vocabulary.lemma,
                Vocabulary.definition_text,
            )
            .join(Vocabulary, Vocabulary.id == UserVocabulary.vocabulary_id)
            .where(
                UserVocabulary.user_id == user_id,
                UserVocabulary.id.in_(list(user_vocabulary_ids)),
                Vocabulary.is_active.is_(True),
            )
        )
        return {
            row[0]: EnrolledWord(
                vocabulary_id=row[1], lemma=row[2], definition_text=row[3]
            )
            for row in await self._session.execute(statement)
        }

    async def prompt_material(
        self, vocabulary_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, str]]:
        """Return ``{vocabulary_id: {language_code: first translation}}``.

        One batched query for the whole page: building prompts per card would
        be the classic N+1 the design explicitly forbids.
        """
        if not vocabulary_ids:
            return {}
        statement = (
            select(
                VocabularyTranslation.vocabulary_id,
                Language.code,
                VocabularyTranslation.translation,
            )
            .join(Language, Language.id == VocabularyTranslation.language_id)
            .where(VocabularyTranslation.vocabulary_id.in_(list(vocabulary_ids)))
            .order_by(
                VocabularyTranslation.vocabulary_id,
                VocabularyTranslation.sense_index,
            )
        )
        material: dict[uuid.UUID, dict[str, str]] = {}
        for vocabulary_id, code, translation in await self._session.execute(statement):
            material.setdefault(vocabulary_id, {}).setdefault(code, translation)
        return material

    async def vocabulary_id_for(
        self, *, user_id: uuid.UUID, user_vocabulary_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Return the catalog word behind an enrollment row."""
        return await self._session.scalar(
            select(Vocabulary.id)
            .join(UserVocabulary, UserVocabulary.vocabulary_id == Vocabulary.id)
            .where(
                UserVocabulary.id == user_vocabulary_id,
                UserVocabulary.user_id == user_id,
            )
        )
