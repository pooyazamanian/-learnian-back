"""Request and response schemas for the review endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class QueueCardResponse(BaseModel):
    """One card, already rendered in its review direction."""

    card_id: uuid.UUID
    vocabulary_id: uuid.UUID
    mode: str
    prompt: str
    answer: str
    state: str
    due_at: datetime


class QueueResponse(BaseModel):
    """A page of the queue with the remaining daily allowance."""

    cards: list[QueueCardResponse]
    new_remaining_today: int
    review_remaining_today: int


class AnswerRequest(BaseModel):
    """One answer for one card.

    ``idempotency_key`` is mandatory: a retried request must not schedule the
    card twice.
    """

    card_id: uuid.UUID
    rating: int = Field(ge=1, le=4, description="1=Again, 2=Hard, 3=Good, 4=Easy")
    idempotency_key: str = Field(min_length=8, max_length=100)
    duration_ms: int | None = Field(default=None, ge=0, le=600000)


class AnswerResponse(BaseModel):
    """The scheduling outcome of one answer."""

    card_id: uuid.UUID
    state: str
    due_at: datetime
    interval_days: int
    stability: float
    difficulty: float
    lapsed: bool
    idempotent_replay: bool
