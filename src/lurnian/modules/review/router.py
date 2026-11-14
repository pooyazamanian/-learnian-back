"""Review endpoints: today's queue and answer submission."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from lurnian.core.config import Settings, get_settings
from lurnian.core.database import get_db_session
from lurnian.modules.auth.presentation.dependencies import Principal
from lurnian.modules.review.schemas import (
    AnswerRequest,
    AnswerResponse,
    QueueCardResponse,
    QueueResponse,
)
from lurnian.modules.review.service import AnswerResult, QueueResult, ReviewService

router = APIRouter(prefix="/review", tags=["Review"])


@router.get(
    "/queue",
    response_model=QueueResponse,
    status_code=status.HTTP_200_OK,
    summary="Get today's review queue",
    description=(
        "Return cards that are due now, limited by the user's daily new-card "
        "and daily review allowances. Cards whose direction lacks the needed "
        "translation are omitted."
    ),
)
async def read_queue(
    principal: Principal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> QueueResponse:
    """Return the next cards to review for the authenticated user."""
    service = ReviewService(session, settings)
    result = await service.queue(user_id=principal.user_id, limit=limit)
    return _queue_response(result)


@router.post(
    "/answers",
    response_model=AnswerResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit a review answer",
    description=(
        "Record one answer, reschedule the card with FSRS and append the review "
        "to the ledger. Replaying the same idempotency key returns the stored "
        "result instead of scheduling again; a stale card version returns 409."
    ),
)
async def submit_answer(
    payload: AnswerRequest,
    principal: Principal,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnswerResponse:
    """Record one answer for one card."""
    service = ReviewService(session, settings)
    result = await service.submit(
        user_id=principal.user_id,
        card_id=payload.card_id,
        rating=payload.rating,
        idempotency_key=payload.idempotency_key,
        duration_ms=payload.duration_ms,
    )
    return _answer_response(result)


def _queue_response(result: QueueResult) -> QueueResponse:
    """Map domain queue cards to the API schema."""
    return QueueResponse(
        cards=[
            QueueCardResponse(
                card_id=card.card_id,
                vocabulary_id=card.vocabulary_id,
                mode=card.mode.value,
                prompt=card.prompt,
                answer=card.answer,
                state=card.state.value,
                due_at=card.due_at,
            )
            for card in result.cards
        ],
        new_remaining_today=result.new_remaining_today,
        review_remaining_today=result.review_remaining_today,
    )


def _answer_response(result: AnswerResult) -> AnswerResponse:
    """Map a scheduling outcome to the API schema."""
    return AnswerResponse(
        card_id=result.card_id,
        state=result.state.value,
        due_at=result.due_at,
        interval_days=result.interval_days,
        stability=result.stability,
        difficulty=result.difficulty,
        lapsed=result.lapsed,
        idempotent_replay=result.replay,
    )
