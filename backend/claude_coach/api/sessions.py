from __future__ import annotations

from datetime import UTC, date as date_cls, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from claude_coach.db.models import GarminActivity, Session as SessionRow, SessionSet, Tested1RM
from claude_coach.db.session import get_db
from claude_coach.services import activity_match
from claude_coach.services.exercise_catalog import catalog as exercise_catalog
from claude_coach.services.plan_repo import load_plan
from claude_coach.services.sessions import (
    PlannedWorkout,
    SessionCreate,
    create_session,
    load_active_plan,
    planned_workout,
    workout_for_date,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])
workouts_router = APIRouter(prefix="/workouts", tags=["workouts"])

Db = Annotated[DbSession, Depends(get_db)]


def _catalog_dict() -> dict[str, Any]:
    return {ex.id: ex.model_dump(mode="json") for ex in exercise_catalog.all()}


# ─── Workouts ─────────────────────────────────────────────────────────────────


class WorkoutTodayResponse(BaseModel):
    date: date_cls
    plan_slug: str | None
    is_rest_day: bool
    workouts: list[PlannedWorkout]


@workouts_router.get("/today", response_model=WorkoutTodayResponse)
def workout_today(
    date: date_cls | None = Query(default=None, description="defaults to today"),
) -> WorkoutTodayResponse:
    day = date or datetime.now(UTC).date()
    active = load_active_plan()
    if not active:
        return WorkoutTodayResponse(date=day, plan_slug=None, is_rest_day=True, workouts=[])
    slug, plan = active
    catalog = _catalog_dict()
    templates = workout_for_date(plan, catalog, day)
    workouts = [planned_workout(slug, plan, catalog, t, day) for t in templates]
    return WorkoutTodayResponse(
        date=day,
        plan_slug=slug,
        is_rest_day=len(workouts) == 0,
        workouts=workouts,
    )


# ─── Sessions ─────────────────────────────────────────────────────────────────


class SetOut(BaseModel):
    block_idx: int
    exercise_id: str
    set_idx: int
    planned_reps: int | None
    actual_reps: int | None
    actual_weight_kg: float | None
    is_warmup: bool
    is_dropset_continuation: bool
    note: str | None


class LinkedActivity(BaseModel):
    activity_id: int
    sport_type: str | None
    duration_s: int | None
    distance_km: float | None
    hr_avg: int | None
    hr_max: int | None


class SessionOut(BaseModel):
    id: int
    plan_slug: str
    workout_template_id: str
    date: date_cls
    status: str
    note: str | None
    started_at: datetime | None
    finished_at: datetime | None
    garmin_activity_id: int | None
    activity_link_source: str | None
    activity: LinkedActivity | None = None
    sets: list[SetOut]


class SessionCreateResponse(BaseModel):
    id: int
    auto_linked_activity_id: int | None
    derived_1rm: list[dict[str, Any]]


class LinkRequest(BaseModel):
    activity_id: int | None  # null = unlink


def _to_session_out(db: DbSession, row: SessionRow) -> SessionOut:
    activity: LinkedActivity | None = None
    if row.garmin_activity_id:
        act = db.get(GarminActivity, row.garmin_activity_id)
        if act:
            activity = LinkedActivity(
                activity_id=act.activity_id,
                sport_type=act.sport_type,
                duration_s=act.duration_s,
                distance_km=act.distance_km,
                hr_avg=act.hr_avg,
                hr_max=act.hr_max,
            )
    return SessionOut(
        id=row.id,
        plan_slug=row.plan_slug,
        workout_template_id=row.workout_template_id,
        date=row.date,
        status=row.status,
        note=row.note,
        started_at=row.started_at,
        finished_at=row.finished_at,
        garmin_activity_id=row.garmin_activity_id,
        activity_link_source=row.activity_link_source,
        activity=activity,
        sets=[
            SetOut(
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
            for s in row.sets
        ],
    )


@router.post("", response_model=SessionCreateResponse, status_code=201)
def post_session(payload: SessionCreate, db: Db) -> SessionCreateResponse:
    plan = load_plan(payload.plan_slug)
    if not plan:
        raise HTTPException(404, f"plan {payload.plan_slug!r} not found")
    template = plan.templates.get(payload.workout_template_id)
    if not template:
        raise HTTPException(
            422, f"template {payload.workout_template_id!r} not in plan {payload.plan_slug!r}"
        )
    result = create_session(db, payload)
    row = db.get(SessionRow, result.id)
    assert row is not None
    linked = activity_match.auto_link(db, row, session_kind=template.kind)
    db.commit()
    return SessionCreateResponse(
        id=result.id,
        auto_linked_activity_id=linked,
        derived_1rm=result.derived_1rm,
    )


@router.get("", response_model=list[SessionOut])
def list_sessions(
    db: Db,
    limit: int = Query(default=50, ge=1, le=500),
    start: date_cls | None = Query(default=None),
    end: date_cls | None = Query(default=None),
) -> list[SessionOut]:
    stmt = select(SessionRow)
    if start:
        stmt = stmt.where(SessionRow.date >= start)
    if end:
        stmt = stmt.where(SessionRow.date <= end)
    stmt = stmt.order_by(SessionRow.date.desc(), SessionRow.id.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [_to_session_out(db, r) for r in rows]


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: int, db: Db) -> SessionOut:
    row = db.get(SessionRow, session_id)
    if not row:
        raise HTTPException(404, f"session {session_id} not found")
    return _to_session_out(db, row)


@router.patch("/{session_id}/activity", response_model=SessionOut)
def patch_activity(session_id: int, payload: LinkRequest, db: Db) -> SessionOut:
    row = db.get(SessionRow, session_id)
    if not row:
        raise HTTPException(404, f"session {session_id} not found")
    try:
        activity_match.set_link(db, row, payload.activity_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    db.refresh(row)
    return _to_session_out(db, row)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: int, db: Db) -> None:
    row = db.get(SessionRow, session_id)
    if not row:
        raise HTTPException(404, f"session {session_id} not found")
    # also drop derived 1RM rows from this session
    db.query(Tested1RM).filter(Tested1RM.session_id == session_id).delete()
    db.query(SessionSet).filter(SessionSet.session_id == session_id).delete()
    db.delete(row)
    db.commit()


# ─── Tested 1RM history ───────────────────────────────────────────────────────


class OneRMRow(BaseModel):
    exercise_id: str
    date: date_cls
    weight_kg: float
    reps_done: int
    estimated_1rm: float
    source: str


@router.get("/exercises/{exercise_id}/history", response_model=list[OneRMRow])
def exercise_history(
    exercise_id: str,
    db: Db,
    limit: int = Query(default=20, ge=1, le=200),
    since_days: int = Query(default=180, ge=1, le=3650),
) -> list[OneRMRow]:
    cutoff = (datetime.now(UTC).date() - timedelta(days=since_days))
    rows = db.execute(
        select(Tested1RM)
        .where(Tested1RM.exercise_id == exercise_id, Tested1RM.date >= cutoff)
        .order_by(Tested1RM.date.desc())
        .limit(limit)
    ).scalars().all()
    return [
        OneRMRow(
            exercise_id=r.exercise_id,
            date=r.date,
            weight_kg=r.weight_kg,
            reps_done=r.reps_done,
            estimated_1rm=r.estimated_1rm,
            source=r.source,
        )
        for r in rows
    ]
