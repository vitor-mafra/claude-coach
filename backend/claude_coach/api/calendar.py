"""Monthly activity calendar — GymRats-style.

For each day of a month, surfaces what physical activity happened (Garmin
activities + logged strength sessions, deduped when a session links to a Garmin
activity) and whether the day's planned training target was met.

Goal logic: a day's target is the number of templates the active plan schedules
for that weekday. The day is "met" when done_count >= planned_count and
planned_count > 0. planned_count == 0 ⇒ rest day (no judgment).
"""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date as date_cls, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from claude_coach.db.models import (
    GarminActivity,
    MeditationSession,
    Session as SessionRow,
)
from claude_coach.db.session import get_db
from claude_coach.domain.plan import Plan
from claude_coach.services.plan_repo import load_plan
from claude_coach.services.sessions import WEEKDAY_BY_INDEX, load_active_plan

router = APIRouter(prefix="/calendar", tags=["calendar"])

Db = Annotated[DbSession, Depends(get_db)]


# ─── Response shapes ──────────────────────────────────────────────────────────


class CalendarActivity(BaseModel):
    source: str  # "garmin" | "session" | "linked" (session + its Garmin activity)
    kind: str  # "run" | "strength" | "other"
    label: str
    sport_type: str | None = None
    distance_km: float | None = None
    duration_min: int | None = None
    session_id: int | None = None
    activity_id: int | None = None


class CalendarMeditation(BaseModel):
    id: int
    duration_min: int | None = None
    source: str
    note: str | None = None


class CalendarDay(BaseModel):
    date: date_cls
    activities: list[CalendarActivity]
    meditations: list[CalendarMeditation]
    planned_count: int
    done_count: int
    goal_met: bool
    is_rest_day: bool


class CalendarResponse(BaseModel):
    month: str  # "YYYY-MM"
    days: list[CalendarDay]  # only days with activity or a planned target


# ─── Helpers ──────────────────────────────────────────────────────────────────


_SPORT_LABELS: dict[str, str] = {
    "running": "Corrida",
    "treadmill_running": "Corrida (esteira)",
    "indoor_running": "Corrida (indoor)",
    "trail_running": "Trail",
    "strength_training": "Musculação",
    "indoor_cardio": "Cardio",
    "cardio": "Cardio",
    "cycling": "Pedal",
    "indoor_cycling": "Pedal (indoor)",
    "mountain_biking": "MTB",
    "walking": "Caminhada",
    "hiking": "Trilha",
    "swimming": "Natação",
    "lap_swimming": "Natação",
    "open_water_swimming": "Natação (águas abertas)",
    "hiit": "HIIT",
    "yoga": "Yoga",
    "pilates": "Pilates",
}


def _garmin_kind(sport_type: str | None) -> str:
    s = (sport_type or "").lower()
    if "run" in s:
        return "run"
    if "strength" in s or "gym" in s:
        return "strength"
    return "other"


def _garmin_label(sport_type: str | None) -> str:
    if not sport_type:
        return "Atividade"
    return _SPORT_LABELS.get(sport_type.lower(), sport_type.replace("_", " ").capitalize())


def _minutes(duration_s: int | None) -> int | None:
    return round(duration_s / 60) if duration_s else None


# ─── Endpoint ─────────────────────────────────────────────────────────────────


@router.get("", response_model=CalendarResponse)
def calendar(
    db: Db,
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$", description="YYYY-MM"),
) -> CalendarResponse:
    try:
        year, mon = int(month[:4]), int(month[5:7])
        first = date_cls(year, mon, 1)
    except ValueError as exc:
        raise HTTPException(422, "month must be a valid YYYY-MM") from exc
    last = date_cls(year, mon, monthrange(year, mon)[1])

    sessions = (
        db.execute(
            select(SessionRow).where(SessionRow.date >= first, SessionRow.date <= last)
        )
        .scalars()
        .all()
    )
    activities = (
        db.execute(
            select(GarminActivity).where(
                GarminActivity.date >= first, GarminActivity.date <= last
            )
        )
        .scalars()
        .all()
    )
    meditations = (
        db.execute(
            select(MeditationSession).where(
                MeditationSession.date >= first, MeditationSession.date <= last
            )
        )
        .scalars()
        .all()
    )

    # Resolve the active plan once (for the weekly target) and cache plan loads
    # so session labels can come from each session's own plan.
    active = load_active_plan()
    active_plan = active[1] if active else None
    plan_cache: dict[str, Plan | None] = {}

    def get_plan(slug: str) -> Plan | None:
        if slug not in plan_cache:
            plan_cache[slug] = load_plan(slug)
        return plan_cache[slug]

    act_by_id = {a.activity_id: a for a in activities}
    linked_ids = {s.garmin_activity_id for s in sessions if s.garmin_activity_id}

    by_day: dict[date_cls, list[CalendarActivity]] = defaultdict(list)

    # Logged sessions first; if a session links a Garmin activity, fold it in.
    for s in sessions:
        plan = get_plan(s.plan_slug)
        tmpl = plan.templates.get(s.workout_template_id) if plan else None
        kind = (
            tmpl.kind
            if tmpl
            else ("run" if "run" in s.workout_template_id.lower() else "strength")
        )
        label = tmpl.name if tmpl else s.workout_template_id
        linked = act_by_id.get(s.garmin_activity_id) if s.garmin_activity_id else None
        by_day[s.date].append(
            CalendarActivity(
                source="linked" if linked else "session",
                kind=kind,
                label=label,
                sport_type=linked.sport_type if linked else None,
                distance_km=linked.distance_km if linked else None,
                duration_min=_minutes(linked.duration_s) if linked else None,
                session_id=s.id,
                activity_id=linked.activity_id if linked else None,
            )
        )

    # Garmin activities not already represented by a linked session.
    for a in activities:
        if a.activity_id in linked_ids:
            continue
        by_day[a.date].append(
            CalendarActivity(
                source="garmin",
                kind=_garmin_kind(a.sport_type),
                label=_garmin_label(a.sport_type),
                sport_type=a.sport_type,
                distance_km=a.distance_km,
                duration_min=_minutes(a.duration_s),
                activity_id=a.activity_id,
            )
        )

    # Meditation is a separate track — grouped per day, never counted toward the
    # training target.
    meds_by_day: dict[date_cls, list[CalendarMeditation]] = defaultdict(list)
    for m in meditations:
        meds_by_day[m.date].append(
            CalendarMeditation(
                id=m.id, duration_min=m.duration_min, source=m.source, note=m.note
            )
        )

    days: list[CalendarDay] = []
    d = first
    while d <= last:
        acts = by_day.get(d, [])
        meds = meds_by_day.get(d, [])
        planned = (
            len(active_plan.schedule.get(WEEKDAY_BY_INDEX[d.weekday()], []))
            if active_plan
            else 0
        )
        done = len(acts)
        if acts or meds or planned:
            days.append(
                CalendarDay(
                    date=d,
                    activities=acts,
                    meditations=meds,
                    planned_count=planned,
                    done_count=done,
                    goal_met=planned > 0 and done >= planned,
                    is_rest_day=planned == 0,
                )
            )
        d += timedelta(days=1)

    return CalendarResponse(month=month, days=days)
