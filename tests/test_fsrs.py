"""Unit tests for the FSRS scheduler (pure functions, no database)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from lurnian.core.enums import FsrsState
from lurnian.modules.review.fsrs import (
    SchedulingInput,
    interval_for_retention,
    retrievability,
    schedule,
)

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
CARD_ID = uuid.UUID("0190f000-0000-7000-8000-000000000001")


def _input(
    *,
    state: FsrsState,
    stability: float = 0.0,
    difficulty: float = 0.0,
    last_reviewed_at: datetime | None = None,
    fuzz: bool = False,
) -> SchedulingInput:
    return SchedulingInput(
        state=state,
        stability=stability,
        difficulty=difficulty,
        learning_step=0,
        last_reviewed_at=last_reviewed_at,
        desired_retention=0.9,
        maximum_interval_days=36500,
        learning_steps=(1, 10),
        relearning_steps=(10,),
        enable_fuzz=fuzz,
    )


def test_new_card_with_good_advances_a_learning_step() -> None:
    outcome = schedule(
        current=_input(state=FsrsState.NEW), rating=3, reviewed_at=NOW, card_id=CARD_ID
    )
    assert outcome.state is FsrsState.LEARNING
    assert outcome.learning_step == 1
    assert outcome.due_at == NOW + timedelta(minutes=10)
    assert outcome.interval_days == 0


def test_new_card_with_easy_graduates_immediately() -> None:
    outcome = schedule(
        current=_input(state=FsrsState.NEW), rating=4, reviewed_at=NOW, card_id=CARD_ID
    )
    assert outcome.state is FsrsState.REVIEW
    assert outcome.interval_days >= 1
    assert outcome.due_at > NOW


def test_again_on_a_review_card_lapses() -> None:
    previous = NOW - timedelta(days=5)
    outcome = schedule(
        current=_input(
            state=FsrsState.REVIEW,
            stability=10.0,
            difficulty=5.0,
            last_reviewed_at=previous,
        ),
        rating=1,
        reviewed_at=NOW,
        card_id=CARD_ID,
    )
    assert outcome.state is FsrsState.RELEARNING
    assert outcome.lapsed
    assert outcome.elapsed_days == 5
    assert outcome.due_at == NOW + timedelta(minutes=10)


def test_easy_interval_is_longer_than_good_interval() -> None:
    previous = NOW - timedelta(days=5)
    base = _input(
        state=FsrsState.REVIEW,
        stability=10.0,
        difficulty=5.0,
        last_reviewed_at=previous,
    )
    good = schedule(current=base, rating=3, reviewed_at=NOW, card_id=CARD_ID)
    easy = schedule(current=base, rating=4, reviewed_at=NOW, card_id=CARD_ID)
    assert easy.interval_days > good.interval_days


def test_interval_respects_the_retention_target() -> None:
    shorter = interval_for_retention(
        stability=30.0, desired_retention=0.97, maximum_interval_days=36500
    )
    longer = interval_for_retention(
        stability=30.0, desired_retention=0.80, maximum_interval_days=36500
    )
    assert shorter < longer


def test_fuzz_is_deterministic_for_a_card_and_day() -> None:
    current = _input(
        state=FsrsState.REVIEW,
        stability=40.0,
        difficulty=4.0,
        last_reviewed_at=NOW - timedelta(days=10),
        fuzz=True,
    )
    first = schedule(current=current, rating=3, reviewed_at=NOW, card_id=CARD_ID)
    second = schedule(current=current, rating=3, reviewed_at=NOW, card_id=CARD_ID)
    assert first.interval_days == second.interval_days


def test_retrievability_decreases_over_time() -> None:
    fresh = retrievability(elapsed_days=1, stability=10)
    stale = retrievability(elapsed_days=30, stability=10)
    assert 0.0 < stale < fresh <= 1.0


@pytest.mark.parametrize("rating", [0, 5])
def test_rating_outside_the_scale_is_rejected(rating: int) -> None:
    with pytest.raises(ValueError):
        schedule(
            current=_input(state=FsrsState.NEW),
            rating=rating,
            reviewed_at=NOW,
            card_id=CARD_ID,
        )
