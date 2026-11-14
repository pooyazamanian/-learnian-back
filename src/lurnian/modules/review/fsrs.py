"""FSRS scheduler: pure functions, no database and no clock assumptions.

The scheduler is deliberately side-effect free: it receives the current state,
the rating and the reference time, and returns the next state. That makes the
algorithm testable and replayable, which is the whole point of storing a
before/after snapshot on every review.

Algorithm: FSRS-5 formulas with the published default weights. The effective
weights are stored in ``fsrs_parameters`` and snapshotted per review, so a
future version can be introduced without rewriting history.
"""

from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from lurnian.core.enums import FsrsState

#: Algorithm version written into new states and review rows.
FSRS_ALGORITHM_VERSION: Final = "FSRS-5"

#: Published FSRS-5 default weights (19 values).
DEFAULT_WEIGHTS: Final[tuple[float, ...]] = (
    0.40255,
    1.18385,
    3.173,
    15.69105,
    7.1949,
    0.5345,
    1.4604,
    0.0046,
    1.54575,
    0.1192,
    1.01925,
    1.9395,
    0.11,
    0.29605,
    2.2698,
    0.2315,
    2.9898,
    0.51655,
    0.6621,
)

#: Decay and scale of the forgetting curve in FSRS-5.
DECAY: Final = -0.5
FACTOR: Final = 19.0 / 81.0

MIN_DIFFICULTY: Final = 1.0
MAX_DIFFICULTY: Final = 10.0
MIN_STABILITY: Final = 0.01
MIN_RATING: Final = 1
MAX_RATING: Final = 4

#: Any interval longer than this is fuzzed; short intervals stay exact.
FUZZ_THRESHOLD_DAYS: Final = 2.0
FUZZ_SPREAD: Final = 0.05


@dataclass(frozen=True, slots=True)
class SchedulingInput:
    """Everything the scheduler needs to know about one card."""

    state: FsrsState
    stability: float
    difficulty: float
    learning_step: int
    last_reviewed_at: datetime | None
    desired_retention: float
    maximum_interval_days: int
    learning_steps: tuple[int, ...]
    relearning_steps: tuple[int, ...]
    enable_fuzz: bool


@dataclass(frozen=True, slots=True)
class SchedulingResult:
    """The complete next state, ready to be persisted and snapshotted."""

    state: FsrsState
    stability: float
    difficulty: float
    due_at: datetime
    interval_days: int
    learning_step: int
    elapsed_days: int
    lapsed: bool


def retrievability(*, elapsed_days: float, stability: float) -> float:
    """Return the probability of recall after ``elapsed_days``.

    A zero stability means the card has never been successfully recalled, so
    retrievability is zero rather than undefined.
    """
    if stability <= 0:
        return 0.0
    return (1.0 + FACTOR * max(elapsed_days, 0.0) / stability) ** DECAY


def initial_difficulty(rating: int, weights: tuple[float, ...]) -> float:
    """Return the difficulty of a card's first answer."""
    difficulty = weights[4] - math.exp(weights[5] * (rating - 1)) + 1.0
    return _clamp_difficulty(difficulty)


def next_difficulty(
    *, difficulty: float, rating: int, weights: tuple[float, ...]
) -> float:
    """Return the difficulty after an answer, with mean reversion."""
    updated = difficulty - weights[6] * (rating - 3)
    reverted = weights[7] * initial_difficulty(4, weights) + (1 - weights[7]) * updated
    return _clamp_difficulty(reverted)


def interval_for_retention(
    *,
    stability: float,
    desired_retention: float,
    maximum_interval_days: int,
) -> int:
    """Return the whole-day interval that hits ``desired_retention``."""
    target = max(min(desired_retention, 0.99), 0.70)
    interval = stability / FACTOR * (target ** (1.0 / DECAY) - 1.0)
    whole_days = max(1, round(interval))
    return min(whole_days, max(1, maximum_interval_days))


def fuzz_interval(interval_days: int, *, seed: uuid.UUID, day: int) -> int:
    """Return a deterministically fuzzed interval.

    Determinism matters: the same card reviewed on the same day must produce
    the same interval in tests and in production.
    """
    if interval_days <= FUZZ_THRESHOLD_DAYS:
        return interval_days
    jitter = random.Random(f"{seed}:{day}")  # noqa: S311 - not security sensitive
    delta = int(round(interval_days * FUZZ_SPREAD))
    if delta < 1:
        return interval_days
    return max(1, interval_days + jitter.randint(-delta, delta))


def schedule(
    *,
    current: SchedulingInput,
    rating: int,
    reviewed_at: datetime,
    card_id: uuid.UUID,
    weights: tuple[float, ...] = DEFAULT_WEIGHTS,
) -> SchedulingResult:
    """Return the next scheduling state for one answer.

    The state machine follows the design document: new cards walk the learning
    steps, review cards advance with the FSRS stability update, and ``Again``
    on a review card is the only path that increments lapses.
    """
    if not MIN_RATING <= rating <= MAX_RATING:
        raise ValueError(f"rating must be between 1 and 4, got {rating}")
    if len(weights) < 19:
        raise ValueError("FSRS weights need at least 19 values")

    elapsed_days = _elapsed_days(current.last_reviewed_at, reviewed_at)
    if current.state is FsrsState.NEW:
        return _schedule_new(
            current=current,
            rating=rating,
            reviewed_at=reviewed_at,
            card_id=card_id,
            weights=weights,
        )
    if current.state in (FsrsState.LEARNING, FsrsState.RELEARNING):
        return _schedule_learning(
            current=current,
            rating=rating,
            reviewed_at=reviewed_at,
            card_id=card_id,
            weights=weights,
            elapsed_days=elapsed_days,
        )
    return _schedule_review(
        current=current,
        rating=rating,
        reviewed_at=reviewed_at,
        card_id=card_id,
        weights=weights,
        elapsed_days=elapsed_days,
    )


def _schedule_new(
    *,
    current: SchedulingInput,
    rating: int,
    reviewed_at: datetime,
    card_id: uuid.UUID,
    weights: tuple[float, ...],
) -> SchedulingResult:
    """First answer of a card: seed stability and difficulty, then place it."""
    stability = max(weights[rating - 1], MIN_STABILITY)
    difficulty = initial_difficulty(rating, weights)

    if rating == 1:
        return _stay_in_learning(
            current=current,
            reviewed_at=reviewed_at,
            stability=stability,
            difficulty=difficulty,
            step=0,
            steps=current.learning_steps,
            state=FsrsState.LEARNING,
            elapsed_days=0,
        )
    if rating == 2:
        return _stay_in_learning(
            current=current,
            reviewed_at=reviewed_at,
            stability=stability,
            difficulty=difficulty,
            step=0,
            steps=current.learning_steps,
            state=FsrsState.LEARNING,
            elapsed_days=0,
        )

    next_step = current.learning_step + 1
    if rating == 3 and next_step < len(current.learning_steps):
        return _stay_in_learning(
            current=current,
            reviewed_at=reviewed_at,
            stability=stability,
            difficulty=difficulty,
            step=next_step,
            steps=current.learning_steps,
            state=FsrsState.LEARNING,
            elapsed_days=0,
        )

    return _graduate(
        current=current,
        reviewed_at=reviewed_at,
        card_id=card_id,
        stability=stability,
        difficulty=difficulty,
        elapsed_days=0,
    )


def _schedule_learning(
    *,
    current: SchedulingInput,
    rating: int,
    reviewed_at: datetime,
    card_id: uuid.UUID,
    weights: tuple[float, ...],
    elapsed_days: int,
) -> SchedulingResult:
    """Card is in learning or relearning: advance a step or graduate."""
    steps = (
        current.relearning_steps
        if current.state is FsrsState.RELEARNING
        else current.learning_steps
    )
    stability = _short_term_stability(
        stability=current.stability,
        rating=rating,
        weights=weights,
        fallback=weights[rating - 1],
    )
    difficulty = (
        current.difficulty
        if current.difficulty > 0
        else initial_difficulty(rating, weights)
    )

    if rating == 1:
        return _stay_in_learning(
            current=current,
            reviewed_at=reviewed_at,
            stability=stability,
            difficulty=difficulty,
            step=0,
            steps=steps,
            state=current.state,
            elapsed_days=elapsed_days,
        )
    if rating == 2:
        return _stay_in_learning(
            current=current,
            reviewed_at=reviewed_at,
            stability=stability,
            difficulty=difficulty,
            step=min(current.learning_step, len(steps) - 1),
            steps=steps,
            state=current.state,
            elapsed_days=elapsed_days,
        )

    next_step = current.learning_step + 1
    if rating == 3 and next_step < len(steps):
        return _stay_in_learning(
            current=current,
            reviewed_at=reviewed_at,
            stability=stability,
            difficulty=difficulty,
            step=next_step,
            steps=steps,
            state=current.state,
            elapsed_days=elapsed_days,
        )

    return _graduate(
        current=current,
        reviewed_at=reviewed_at,
        card_id=card_id,
        stability=stability,
        difficulty=difficulty,
        elapsed_days=elapsed_days,
    )


def _schedule_review(
    *,
    current: SchedulingInput,
    rating: int,
    reviewed_at: datetime,
    card_id: uuid.UUID,
    weights: tuple[float, ...],
    elapsed_days: int,
) -> SchedulingResult:
    """Stable card: apply the success or lapse stability update."""
    recall = retrievability(elapsed_days=elapsed_days, stability=current.stability)
    difficulty = next_difficulty(
        difficulty=current.difficulty, rating=rating, weights=weights
    )

    if rating == 1:
        stability = _lapse_stability(
            stability=current.stability,
            difficulty=current.difficulty,
            recall=recall,
            weights=weights,
        )
        steps = current.relearning_steps or (10,)
        return SchedulingResult(
            state=FsrsState.RELEARNING,
            stability=max(stability, MIN_STABILITY),
            difficulty=difficulty,
            due_at=reviewed_at + timedelta(minutes=steps[0]),
            interval_days=0,
            learning_step=0,
            elapsed_days=elapsed_days,
            lapsed=True,
        )

    stability = _success_stability(
        stability=current.stability,
        difficulty=current.difficulty,
        recall=recall,
        rating=rating,
        weights=weights,
    )
    return _graduate(
        current=SchedulingInput(
            state=FsrsState.REVIEW,
            stability=stability,
            difficulty=difficulty,
            learning_step=current.learning_step,
            last_reviewed_at=current.last_reviewed_at,
            desired_retention=current.desired_retention,
            maximum_interval_days=current.maximum_interval_days,
            learning_steps=current.learning_steps,
            relearning_steps=current.relearning_steps,
            enable_fuzz=current.enable_fuzz,
        ),
        reviewed_at=reviewed_at,
        card_id=card_id,
        stability=stability,
        difficulty=difficulty,
        elapsed_days=elapsed_days,
    )


def _graduate(
    *,
    current: SchedulingInput,
    reviewed_at: datetime,
    card_id: uuid.UUID,
    stability: float,
    difficulty: float,
    elapsed_days: int,
) -> SchedulingResult:
    """Move the card to ``review`` with an interval derived from stability."""
    interval = interval_for_retention(
        stability=stability,
        desired_retention=current.desired_retention,
        maximum_interval_days=current.maximum_interval_days,
    )
    if current.enable_fuzz:
        interval = fuzz_interval(
            interval, seed=card_id, day=reviewed_at.date().toordinal()
        )
    return SchedulingResult(
        state=FsrsState.REVIEW,
        stability=max(stability, MIN_STABILITY),
        difficulty=difficulty,
        due_at=reviewed_at + timedelta(days=interval),
        interval_days=interval,
        learning_step=0,
        elapsed_days=elapsed_days,
        lapsed=False,
    )


def _stay_in_learning(
    *,
    current: SchedulingInput,
    reviewed_at: datetime,
    stability: float,
    difficulty: float,
    step: int,
    steps: tuple[int, ...],
    state: FsrsState,
    elapsed_days: int,
) -> SchedulingResult:
    """Keep the card in the short-term steps for another pass."""
    minutes = steps[min(step, len(steps) - 1)] if steps else 10
    return SchedulingResult(
        state=state,
        stability=max(stability, MIN_STABILITY),
        difficulty=difficulty,
        due_at=reviewed_at + timedelta(minutes=minutes),
        interval_days=0,
        learning_step=step,
        elapsed_days=elapsed_days,
        lapsed=False,
    )


def _success_stability(
    *,
    stability: float,
    difficulty: float,
    recall: float,
    rating: int,
    weights: tuple[float, ...],
) -> float:
    """FSRS-5 stability increase after a successful recall."""
    hard_penalty = weights[15] if rating == 2 else 1.0
    easy_bonus = weights[16] if rating == 4 else 1.0
    growth = (
        math.exp(weights[8])
        * (11.0 - difficulty)
        * (max(stability, MIN_STABILITY) ** -weights[9])
        * (math.exp(weights[10] * (1.0 - recall)) - 1.0)
        * hard_penalty
        * easy_bonus
    )
    return max(stability * (1.0 + growth), MIN_STABILITY)


def _lapse_stability(
    *,
    stability: float,
    difficulty: float,
    recall: float,
    weights: tuple[float, ...],
) -> float:
    """FSRS-5 stability after a lapse (``Again`` on a review card)."""
    value = (
        weights[11]
        * (max(difficulty, MIN_DIFFICULTY) ** -weights[12])
        * ((max(stability, MIN_STABILITY) + 1.0) ** weights[13] - 1.0)
        * math.exp(weights[14] * (1.0 - recall))
    )
    return max(value, MIN_STABILITY)


def _short_term_stability(
    *,
    stability: float,
    rating: int,
    weights: tuple[float, ...],
    fallback: float,
) -> float:
    """FSRS-5 same-day stability update for learning steps."""
    if stability <= 0:
        return max(fallback, MIN_STABILITY)
    return max(
        stability * math.exp(weights[17] * (rating - 3 + weights[18])),
        MIN_STABILITY,
    )


def _elapsed_days(last_reviewed_at: datetime | None, reviewed_at: datetime) -> int:
    """Whole days since the previous answer, never negative."""
    if last_reviewed_at is None:
        return 0
    delta = reviewed_at - _as_utc(last_reviewed_at)
    return max(0, delta.days)


def _as_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC (the database always returns aware ones)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _clamp_difficulty(value: float) -> float:
    """Keep difficulty inside the 1..10 scale FSRS is defined on."""
    return min(max(value, MIN_DIFFICULTY), MAX_DIFFICULTY)
