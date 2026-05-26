"""Session service: derive today's workout from the active plan, create a
Session+SessionSets, compute Epley estimates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date as date_cls, datetime
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from claude_coach.db.models import Session as SessionRow, SessionSet, Tested1RM
from claude_coach.domain.calculations import epley_one_rm
from claude_coach.domain.plan import (
    BiSetBlock,
    DropsetBlock,
    MetaRepsBlock,
    Plan,
    PyramidBlock,
    WorkoutTemplate,
)
from claude_coach.domain.profile import Weekday
from claude_coach.services.plan_repo import list_plan_slugs, load_plan

log = structlog.get_logger(__name__)

WEEKDAY_BY_INDEX: list[Weekday] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ─── DTOs returned to the API ─────────────────────────────────────────────────


class PlannedSet(BaseModel):
    set_idx: int
    planned_reps: int | None = None
    is_warmup: bool = False


class PlannedExercise(BaseModel):
    block_idx: int
    exercise_id: str
    exercise_name: str
    sets: list[PlannedSet]
    rest_seconds: int | None = None
    kind: str  # meta_reps / pyramid / biset / dropset / etc
    notes: str | None = None


class PlannedRunSegment(BaseModel):
    block_idx: int
    block_kind: str  # interval_run | continuous_run | fartlek
    repeats: int
    distance_km: float | None = None
    duration_min: float | None = None
    hr_zone: str  # Z1..Z5
    note: str | None = None


class PlannedWorkout(BaseModel):
    plan_slug: str
    template_id: str
    name: str
    kind: str  # strength | run
    date: date_cls
    exercises: list[PlannedExercise]
    run_segments: list[PlannedRunSegment] = []


# ─── Plan → PlannedWorkout ────────────────────────────────────────────────────


def _weekday(d: date_cls) -> Weekday:
    return WEEKDAY_BY_INDEX[d.weekday()]


def _exercise_name(catalog: dict[str, Any], exercise_id: str | None, fallback: str) -> str:
    if exercise_id and exercise_id in catalog:
        return catalog[exercise_id].get("name", exercise_id)
    return fallback


def _flatten_block(
    block: Any,
    block_idx: int,
    catalog: dict[str, Any],
) -> list[PlannedExercise]:
    """Convert a Plan Block into 1 or more PlannedExercise entries.

    Bi-sets explode into one PlannedExercise per partner exercise sharing the
    same `block_idx`, so the UI can render them side by side.
    """
    rest = (block.rest.seconds if getattr(block, "rest", None) else None) or None

    if isinstance(block, MetaRepsBlock):
        return [
            PlannedExercise(
                block_idx=block_idx,
                exercise_id=block.exercise.exercise_id or block.exercise.raw_name,
                exercise_name=_exercise_name(
                    catalog, block.exercise.exercise_id, block.exercise.raw_name
                ),
                sets=[PlannedSet(set_idx=i + 1, planned_reps=block.reps) for i in range(block.sets)],
                rest_seconds=rest,
                kind="meta_reps",
            )
        ]
    if isinstance(block, PyramidBlock):
        return [
            PlannedExercise(
                block_idx=block_idx,
                exercise_id=block.exercise.exercise_id or block.exercise.raw_name,
                exercise_name=_exercise_name(
                    catalog, block.exercise.exercise_id, block.exercise.raw_name
                ),
                sets=[
                    PlannedSet(set_idx=i + 1, planned_reps=reps)
                    for i, reps in enumerate(block.reps_per_set)
                ],
                rest_seconds=rest,
                kind="pyramid",
            )
        ]
    if isinstance(block, BiSetBlock):
        out: list[PlannedExercise] = []
        for partner in block.exercises:
            out.append(
                PlannedExercise(
                    block_idx=block_idx,
                    exercise_id=partner.exercise.exercise_id or partner.exercise.raw_name,
                    exercise_name=_exercise_name(
                        catalog, partner.exercise.exercise_id, partner.exercise.raw_name
                    ),
                    sets=[
                        PlannedSet(set_idx=i + 1, planned_reps=partner.reps)
                        for i in range(block.rounds)
                    ],
                    rest_seconds=rest,
                    kind="biset",
                )
            )
        return out
    if isinstance(block, DropsetBlock):
        return [
            PlannedExercise(
                block_idx=block_idx,
                exercise_id=block.exercise.exercise_id or block.exercise.raw_name,
                exercise_name=_exercise_name(
                    catalog, block.exercise.exercise_id, block.exercise.raw_name
                ),
                sets=[PlannedSet(set_idx=i + 1) for i in range(block.sets)],
                rest_seconds=rest,
                kind="dropset",
                notes=block.description,
            )
        ]
    # Tabata: skip silently (not strength-loggable in MVP).
    # Run blocks: emitted as run_segments separately (see _flatten_run_segments).
    return []


def _flatten_run_segments(template: WorkoutTemplate) -> list[PlannedRunSegment]:
    out: list[PlannedRunSegment] = []
    for idx, block in enumerate(template.blocks):
        if block.kind not in ("interval_run", "continuous_run", "fartlek"):
            continue
        for seg in block.segments:
            out.append(
                PlannedRunSegment(
                    block_idx=idx,
                    block_kind=block.kind,
                    repeats=seg.repeats,
                    distance_km=seg.distance_km,
                    duration_min=seg.duration_min,
                    hr_zone=seg.hr_zone,
                    note=seg.note,
                )
            )
    return out


def workout_for_date(
    plan: Plan,
    catalog: dict[str, Any],
    day: date_cls,
) -> list[WorkoutTemplate]:
    """Return ordered list of templates scheduled on `day` (empty = rest day)."""
    wd = _weekday(day)
    template_ids = plan.schedule.get(wd, [])
    return [plan.templates[tid] for tid in template_ids if tid in plan.templates]


def planned_workout(
    plan_slug: str,
    plan: Plan,
    catalog: dict[str, Any],
    template: WorkoutTemplate,
    day: date_cls,
) -> PlannedWorkout:
    exercises: list[PlannedExercise] = []
    for idx, block in enumerate(template.blocks):
        exercises.extend(_flatten_block(block, idx, catalog))
    return PlannedWorkout(
        plan_slug=plan_slug,
        template_id=template.template_id,
        name=template.name,
        kind=template.kind,
        date=day,
        exercises=exercises,
        run_segments=_flatten_run_segments(template),
    )


# ─── Persistence ──────────────────────────────────────────────────────────────


class SetInput(BaseModel):
    block_idx: int
    exercise_id: str
    set_idx: int
    planned_reps: int | None = None
    actual_reps: int | None = None
    actual_weight_kg: float | None = None
    is_warmup: bool = False
    is_dropset_continuation: bool = False
    note: str | None = None


class SessionCreate(BaseModel):
    plan_slug: str
    workout_template_id: str
    date: date_cls
    status: str = "done"
    note: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    sets: list[SetInput]


@dataclass
class SessionResult:
    id: int
    derived_1rm: list[dict[str, Any]]


def _best_set_per_exercise(
    sets: Iterable[SetInput],
) -> dict[str, tuple[float, int]]:
    """Return {exercise_id: (weight_kg, reps)} for the heaviest-by-Epley working set."""
    best: dict[str, tuple[float, int, float]] = {}
    for s in sets:
        if s.is_warmup or not s.actual_reps or not s.actual_weight_kg:
            continue
        try:
            est = epley_one_rm(s.actual_weight_kg, s.actual_reps)
        except ValueError:
            continue
        current = best.get(s.exercise_id)
        if current is None or est > current[2]:
            best[s.exercise_id] = (s.actual_weight_kg, s.actual_reps, est)
    return {k: (v[0], v[1]) for k, v in best.items()}


def create_session(db: DbSession, payload: SessionCreate) -> SessionResult:
    row = SessionRow(
        plan_slug=payload.plan_slug,
        workout_template_id=payload.workout_template_id,
        date=payload.date,
        status=payload.status,
        note=payload.note,
        started_at=payload.started_at,
        finished_at=payload.finished_at,
    )
    db.add(row)
    db.flush()

    for s in payload.sets:
        db.add(
            SessionSet(
                session_id=row.id,
                block_idx=s.block_idx,
                exercise_id=s.exercise_id,
                set_idx=s.set_idx,
                planned_reps=s.planned_reps,
                actual_reps=s.actual_reps,
                actual_weight_kg=s.actual_weight_kg,
                is_warmup=s.is_warmup,
                is_dropset_continuation=s.is_dropset_continuation,
                note=s.note,
            )
        )

    derived: list[dict[str, Any]] = []
    for exercise_id, (weight, reps) in _best_set_per_exercise(payload.sets).items():
        est = epley_one_rm(weight, reps)
        db.add(
            Tested1RM(
                exercise_id=exercise_id,
                date=payload.date,
                weight_kg=weight,
                reps_done=reps,
                estimated_1rm=est,
                source="derived",
                session_id=row.id,
            )
        )
        derived.append(
            {"exercise_id": exercise_id, "weight_kg": weight, "reps": reps, "estimated_1rm": est}
        )

    db.commit()
    db.refresh(row)
    log.info(
        "session.created",
        session_id=row.id,
        plan=payload.plan_slug,
        template=payload.workout_template_id,
        sets=len(payload.sets),
        derived_1rm_count=len(derived),
    )
    return SessionResult(id=row.id, derived_1rm=derived)


def now_utc() -> datetime:
    return datetime.now(UTC)


def first_active_plan_slug() -> str | None:
    slugs = list_plan_slugs()
    return slugs[0] if slugs else None


def load_active_plan() -> tuple[str, Plan] | None:
    slug = first_active_plan_slug()
    if not slug:
        return None
    plan = load_plan(slug)
    if not plan:
        return None
    return slug, plan
