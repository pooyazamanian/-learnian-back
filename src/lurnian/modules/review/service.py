"""Review service: serve today's queue and record answers.

Two invariants drive the design:

* one answer per ``idempotency_key`` - a retried request returns the stored
  result instead of scheduling the card twice;
* one writer per card version - the state update is conditional on
  ``row_version``, so two devices answering the same card cannot both win.

The service touches Review tables directly, Platform's outbox to publish a
domain event, and reads word/profile data through the Learning and Profile
query interfaces.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lurnian.core.config import Settings
from lurnian.core.enums import FsrsState, ReviewCardMode
from lurnian.core.exceptions import ConflictError, NotFoundError
from lurnian.modules.learning.service import LearningQuery
from lurnian.modules.platform.models import OutboxEvent
from lurnian.modules.profile.service import ProfileQuery
from lurnian.modules.review.fsrs import (
    DEFAULT_WEIGHTS,
    FSRS_ALGORITHM_VERSION,
    SchedulingInput,
    schedule,
)
from lurnian.modules.review.models import (
    FsrsCardState,
    FsrsSettings,
    ReviewCard,
    ReviewHistory,
)

#: Used until the user has a row in ``fsrs_settings``.
DEFAULT_DESIRED_RETENTION = 0.9
DEFAULT_MAXIMUM_INTERVAL_DAYS = 36500
DEFAULT_LEARNING_STEPS: tuple[int, ...] = (1, 10)
DEFAULT_RELEARNING_STEPS: tuple[int, ...] = (10,)


@dataclass(frozen=True, slots=True)
class QueueCard:
    """One card ready to be shown, already rendered for its direction."""

    card_id: uuid.UUID
    vocabulary_id: uuid.UUID
    mode: ReviewCardMode
    prompt: str
    answer: str
    state: FsrsState
    due_at: datetime


@dataclass(frozen=True, slots=True)
class QueueResult:
    """A page of the queue plus the remaining daily allowance."""

    cards: tuple[QueueCard, ...]
    new_remaining_today: int
    review_remaining_today: int


@dataclass(frozen=True, slots=True)
class AnswerResult:
    """Outcome of recording one answer."""

    card_id: uuid.UUID
    state: FsrsState
    due_at: datetime
    interval_days: int
    stability: float
    difficulty: float
    lapsed: bool
    replay: bool


class ReviewService:
    """Use cases of the Review domain."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._learning = LearningQuery(session)
        self._profile = ProfileQuery(session)

    async def queue(self, *, user_id: uuid.UUID, limit: int = 20) -> QueueResult:
        """Return due cards, honouring the user's daily new/review caps."""
        study = await self._learning.study_settings(user_id)
        today = await self._today(user_id)

        reviewed_new = await self._count_reviews(user_id, today, only_new=True)
        reviewed_total = await self._count_reviews(user_id, today, only_new=False)
        new_remaining = max(0, study.daily_new_cards - reviewed_new)
        review_remaining = max(0, study.daily_review_limit - reviewed_total)

        statement = (
            select(
                ReviewCard.id,
                ReviewCard.mode,
                ReviewCard.user_vocabulary_id,
                FsrsCardState.state,
                FsrsCardState.due_at,
            )
            .join(FsrsCardState, FsrsCardState.card_id == ReviewCard.id)
            .where(
                ReviewCard.user_id == user_id,
                ReviewCard.is_suspended.is_(False),
                FsrsCardState.user_id == user_id,
                FsrsCardState.due_at <= func.now(),
            )
            .order_by(
                case((FsrsCardState.state == FsrsState.NEW, 1), else_=0),
                FsrsCardState.due_at,
                ReviewCard.id,
            )
            .limit(limit * 4)
        )
        rows = list(await self._session.execute(statement))
        words = await self._learning.enrolled_words(
            user_id=user_id,
            user_vocabulary_ids=[row.user_vocabulary_id for row in rows],
        )
        material = await self._learning.prompt_material(
            [word.vocabulary_id for word in words.values()]
        )

        cards: list[QueueCard] = []
        new_used = 0
        review_used = 0
        for row in rows:
            if len(cards) >= limit:
                break
            word = words.get(row.user_vocabulary_id)
            if word is None:
                continue
            is_new = row.state == FsrsState.NEW
            if is_new and new_used >= new_remaining:
                continue
            if not is_new and review_used >= review_remaining:
                continue
            rendered = _render(
                mode=row.mode,
                lemma=word.lemma,
                definition=word.definition_text,
                translations=material.get(word.vocabulary_id, {}),
            )
            if rendered is None:
                # A missing translation means this direction is not answerable
                # yet; it must not occupy a slot in the queue.
                continue
            prompt, answer = rendered
            cards.append(
                QueueCard(
                    card_id=row.id,
                    vocabulary_id=word.vocabulary_id,
                    mode=row.mode,
                    prompt=prompt,
                    answer=answer,
                    state=row.state,
                    due_at=row.due_at,
                )
            )
            if is_new:
                new_used += 1
            else:
                review_used += 1

        return QueueResult(
            cards=tuple(cards),
            new_remaining_today=max(0, new_remaining - new_used),
            review_remaining_today=max(0, review_remaining - review_used),
        )

    async def submit(
        self,
        *,
        user_id: uuid.UUID,
        card_id: uuid.UUID,
        rating: int,
        idempotency_key: str,
        duration_ms: int | None = None,
    ) -> AnswerResult:
        """Record one answer and reschedule the card.

        The write path is: conditional state update, append-only history row,
        outbox event, then one commit. Replays are detected by the unique
        ``(user_id, idempotency_key)`` constraint, not by trusting the client.
        """
        replay = await self._replay(user_id, idempotency_key)
        if replay is not None:
            return replay

        row = (
            await self._session.execute(
                select(ReviewCard, FsrsCardState)
                .join(FsrsCardState, FsrsCardState.card_id == ReviewCard.id)
                .where(
                    ReviewCard.id == card_id,
                    ReviewCard.user_id == user_id,
                    FsrsCardState.user_id == user_id,
                )
            )
        ).first()
        if row is None:
            raise NotFoundError("Review card not found")
        card, state = row
        if card.is_suspended:
            raise ConflictError("Card is suspended")

        vocabulary_id = await self._learning.vocabulary_id_for(
            user_id=user_id, user_vocabulary_id=card.user_vocabulary_id
        )
        policy = await self._session.get(FsrsSettings, user_id)
        now = datetime.now(UTC)
        reviewed_on = await self._today(user_id)

        outcome = schedule(
            current=SchedulingInput(
                state=state.state,
                stability=state.stability,
                difficulty=state.difficulty,
                learning_step=state.learning_step,
                last_reviewed_at=state.last_reviewed_at,
                desired_retention=(
                    float(policy.desired_retention)
                    if policy is not None
                    else DEFAULT_DESIRED_RETENTION
                ),
                maximum_interval_days=(
                    policy.maximum_interval_days
                    if policy is not None
                    else DEFAULT_MAXIMUM_INTERVAL_DAYS
                ),
                learning_steps=(
                    tuple(policy.learning_steps)
                    if policy is not None
                    else DEFAULT_LEARNING_STEPS
                ),
                relearning_steps=(
                    tuple(policy.relearning_steps)
                    if policy is not None
                    else DEFAULT_RELEARNING_STEPS
                ),
                enable_fuzz=policy.enable_fuzz if policy is not None else True,
            ),
            rating=rating,
            reviewed_at=now,
            card_id=card_id,
            weights=DEFAULT_WEIGHTS,
        )

        applied = await self._session.execute(
            update(FsrsCardState)
            .where(
                FsrsCardState.card_id == card_id,
                FsrsCardState.user_id == user_id,
                FsrsCardState.row_version == state.row_version,
            )
            .values(
                state=outcome.state,
                due_at=outcome.due_at,
                stability=outcome.stability,
                difficulty=outcome.difficulty,
                reps=state.reps + 1,
                lapses=state.lapses + (1 if outcome.lapsed else 0),
                learning_step=outcome.learning_step,
                elapsed_days=outcome.elapsed_days,
                scheduled_days=outcome.interval_days,
                last_reviewed_at=now,
                algorithm_version=FSRS_ALGORITHM_VERSION,
                row_version=state.row_version + 1,
            )
        )
        if applied.rowcount == 0:
            # Another device answered this card first; the client should reload.
            await self._session.rollback()
            raise ConflictError("Card was updated by another request")

        self._session.add(
            ReviewHistory(
                user_id=user_id,
                card_id=card_id,
                user_vocabulary_id=card.user_vocabulary_id,
                vocabulary_id=vocabulary_id,
                card_mode=card.mode,
                rating=rating,
                reviewed_at=now,
                reviewed_on=reviewed_on,
                state_before=state.state,
                state_after=outcome.state,
                due_before=state.due_at,
                due_after=outcome.due_at,
                stability_before=state.stability,
                stability_after=outcome.stability,
                difficulty_before=state.difficulty,
                difficulty_after=outcome.difficulty,
                elapsed_days=outcome.elapsed_days,
                scheduled_days=outcome.interval_days,
                duration_ms=duration_ms,
                algorithm_version=FSRS_ALGORITHM_VERSION,
                parameters_id=state.parameters_id,
                idempotency_key=idempotency_key,
            )
        )
        self._session.add(
            OutboxEvent(
                aggregate_type="review_card",
                aggregate_id=card_id,
                event_type="review.card.rescheduled",
                payload={
                    "user_id": str(user_id),
                    "card_id": str(card_id),
                    "state": outcome.state.value,
                    "due_at": outcome.due_at.isoformat(),
                },
                dedupe_key=f"review:{idempotency_key}",
            )
        )
        try:
            await self._session.commit()
        except IntegrityError as exc:
            # Lost the idempotency race: return whatever the winner stored.
            await self._session.rollback()
            existing = await self._replay(user_id, idempotency_key)
            if existing is None:
                raise ConflictError("Concurrent review could not be recorded") from exc
            return existing

        return AnswerResult(
            card_id=card_id,
            state=outcome.state,
            due_at=outcome.due_at,
            interval_days=outcome.interval_days,
            stability=outcome.stability,
            difficulty=outcome.difficulty,
            lapsed=outcome.lapsed,
            replay=False,
        )

    async def _replay(
        self, user_id: uuid.UUID, idempotency_key: str
    ) -> AnswerResult | None:
        """Return the stored outcome of an already-processed answer."""
        history = await self._session.scalar(
            select(ReviewHistory).where(
                ReviewHistory.user_id == user_id,
                ReviewHistory.idempotency_key == idempotency_key,
            )
        )
        if history is None or history.due_after is None:
            return None
        return AnswerResult(
            card_id=history.card_id or uuid.UUID(int=0),
            state=history.state_after,
            due_at=history.due_after,
            interval_days=history.scheduled_days or 0,
            stability=history.stability_after or 0.0,
            difficulty=history.difficulty_after or 0.0,
            lapsed=history.state_after == FsrsState.RELEARNING,
            replay=True,
        )

    async def _count_reviews(
        self, user_id: uuid.UUID, day: date, *, only_new: bool
    ) -> int:
        """Count today's answers, optionally only those on new cards."""
        statement = (
            select(func.count())
            .select_from(ReviewHistory)
            .where(
                ReviewHistory.user_id == user_id,
                ReviewHistory.reviewed_on == day,
            )
        )
        if only_new:
            statement = statement.where(ReviewHistory.state_before == FsrsState.NEW)
        return int(await self._session.scalar(statement) or 0)

    async def _today(self, user_id: uuid.UUID) -> date:
        """Return the user's current calendar day."""
        timezone = await self._profile.timezone(user_id)
        return datetime.now(ZoneInfo(timezone)).date()


def _render(
    *,
    mode: ReviewCardMode,
    lemma: str,
    definition: str | None,
    translations: dict[str, str],
) -> tuple[str, str] | None:
    """Build the prompt/answer pair for one direction.

    Returns ``None`` when the data for that direction does not exist yet, so the
    queue never shows an unanswerable card.
    """
    if mode is ReviewCardMode.WORD_TO_FA:
        answer = translations.get("fa")
        return (lemma, answer) if answer else None
    if mode is ReviewCardMode.WORD_TO_EN:
        answer = translations.get("en") or definition
        return (lemma, answer) if answer else None
    if mode is ReviewCardMode.FA_TO_WORD:
        prompt = translations.get("fa")
        return (prompt, lemma) if prompt else None
    if mode is ReviewCardMode.EN_TO_WORD:
        prompt = translations.get("en") or definition
        return (prompt, lemma) if prompt else None
    return None
