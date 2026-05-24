"""Home dashboard aggregator.

One endpoint returns everything the home screen needs so the frontend doesn't
need to chain 5 queries to paint above-the-fold content.
"""

from __future__ import annotations

from datetime import UTC, date as date_cls, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from claude_coach.adapters.garmin import GarminAuthError, adapter as garmin_adapter
from claude_coach.db.models import DailyMetric, GarminActivity, Session as SessionRow
from claude_coach.db.session import get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

Db = Annotated[DbSession, Depends(get_db)]


# ─── Response shapes ──────────────────────────────────────────────────────────


class TodayCard(BaseModel):
    date: date_cls
    sleep_score: int | None
    sleep_duration_min: int | None
    sleep_score_7d_avg: float | None
    body_battery_start: int | None
    body_battery_end: int | None
    body_battery_now: int | None  # alias of end — Garmin's last sample today
    stress_avg: int | None
    stress_7d_avg: float | None
    hrv_avg: float | None
    hrv_7d_avg: float | None
    valid_as_of: datetime | None


class DailyTrendRow(BaseModel):
    date: date_cls
    sleep_score: int | None
    sleep_duration_min: int | None
    hrv_avg: float | None
    body_battery_start: int | None
    body_battery_end: int | None
    stress_avg: int | None


class WeeklyVolumeRow(BaseModel):
    week_start: date_cls
    week_label: str  # "11–17/05"
    strength_sessions: int
    run_count: int
    run_km: float
    run_minutes: int


class BodyBatteryPoint(BaseModel):
    ts: datetime
    level: int


class RecentActivity(BaseModel):
    activity_id: int
    date: date_cls
    sport_type: str | None
    duration_min: int | None
    distance_km: float | None
    hr_avg: int | None


class VO2MaxCard(BaseModel):
    value: float
    measured_at: date_cls


class DashboardResponse(BaseModel):
    today: TodayCard
    trend: list[DailyTrendRow]
    body_battery_intraday: list[BodyBatteryPoint]
    weekly_volume: list[WeeklyVolumeRow]
    recent_activities: list[RecentActivity]
    vo2_max: VO2MaxCard | None = None


# ─── Aggregations ─────────────────────────────────────────────────────────────


def _avg(rows: list[DailyMetric], attr: str) -> float | None:
    vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _today_card(db: DbSession, day: date_cls) -> TodayCard:
    row = db.get(DailyMetric, day)
    prev = (
        db.execute(
            select(DailyMetric)
            .where(DailyMetric.date < day)
            .order_by(DailyMetric.date.desc())
            .limit(7)
        )
        .scalars()
        .all()
    )
    return TodayCard(
        date=day,
        sleep_score=row.sleep_score if row else None,
        sleep_duration_min=row.sleep_duration_min if row else None,
        sleep_score_7d_avg=_avg(prev, "sleep_score"),
        body_battery_start=row.body_battery_start if row else None,
        body_battery_end=row.body_battery_end if row else None,
        body_battery_now=row.body_battery_end if row else None,
        stress_avg=row.stress_avg if row else None,
        stress_7d_avg=_avg(prev, "stress_avg"),
        hrv_avg=row.hrv_avg if row else None,
        hrv_7d_avg=_avg(prev, "hrv_avg"),
        valid_as_of=row.valid_as_of_timestamp if row else None,
    )


def _body_battery_intraday(
    db: DbSession, day: date_cls, days: int = 7
) -> list[BodyBatteryPoint]:
    """Extract per-sample body battery levels from raw_payload over the window."""
    start = day - timedelta(days=days - 1)
    rows = (
        db.execute(
            select(DailyMetric)
            .where(DailyMetric.date >= start, DailyMetric.date <= day)
            .order_by(DailyMetric.date.asc())
        )
        .scalars()
        .all()
    )
    out: list[BodyBatteryPoint] = []
    for r in rows:
        if not r.raw_payload:
            continue
        bb = r.raw_payload.get("body_battery_stress") if isinstance(r.raw_payload, dict) else None
        if not bb:
            continue
        arr = bb.get("body_battery_values_array") or []
        for entry in arr:
            # entry shape: [timestamp_ms, status, level, ...]
            if not isinstance(entry, list) or len(entry) < 3:
                continue
            ts_ms, _status, level = entry[0], entry[1], entry[2]
            if not isinstance(level, int) or not isinstance(ts_ms, int | float):
                continue
            out.append(
                BodyBatteryPoint(
                    ts=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
                    level=int(level),
                )
            )
    out.sort(key=lambda p: p.ts)
    return out


def _trend(db: DbSession, day: date_cls, days: int = 7) -> list[DailyTrendRow]:
    start = day - timedelta(days=days - 1)
    rows = (
        db.execute(
            select(DailyMetric)
            .where(DailyMetric.date >= start, DailyMetric.date <= day)
            .order_by(DailyMetric.date.asc())
        )
        .scalars()
        .all()
    )
    by_date = {r.date: r for r in rows}
    out: list[DailyTrendRow] = []
    for i in range(days):
        d = start + timedelta(days=i)
        r = by_date.get(d)
        out.append(
            DailyTrendRow(
                date=d,
                sleep_score=r.sleep_score if r else None,
                sleep_duration_min=r.sleep_duration_min if r else None,
                hrv_avg=r.hrv_avg if r else None,
                body_battery_start=r.body_battery_start if r else None,
                body_battery_end=r.body_battery_end if r else None,
                stress_avg=r.stress_avg if r else None,
            )
        )
    return out


def _weekly_volume(db: DbSession, day: date_cls, weeks: int = 6) -> list[WeeklyVolumeRow]:
    # Compute the Monday of the current week, then walk back `weeks-1` weeks.
    this_monday = day - timedelta(days=day.weekday())
    earliest_monday = this_monday - timedelta(days=(weeks - 1) * 7)

    sessions = (
        db.execute(
            select(SessionRow)
            .where(SessionRow.date >= earliest_monday, SessionRow.date <= day)
        )
        .scalars()
        .all()
    )
    activities = (
        db.execute(
            select(GarminActivity)
            .where(GarminActivity.date >= earliest_monday, GarminActivity.date <= day)
        )
        .scalars()
        .all()
    )

    out: list[WeeklyVolumeRow] = []
    for i in range(weeks):
        ws = earliest_monday + timedelta(days=i * 7)
        we = ws + timedelta(days=6)
        runs = [
            a
            for a in activities
            if ws <= a.date <= we and (a.sport_type or "").lower().find("run") != -1
        ]
        strength_sess = [
            s
            for s in sessions
            if ws <= s.date <= we
            and "run" not in (s.workout_template_id or "").lower()
        ]
        run_km = round(sum(a.distance_km or 0 for a in runs), 1)
        run_min = sum(round((a.duration_s or 0) / 60) for a in runs)
        label = (
            f"{ws.day:02d}–{we.day:02d}/{we.month:02d}"
            if ws.month == we.month
            else f"{ws.day:02d}/{ws.month:02d}–{we.day:02d}/{we.month:02d}"
        )
        out.append(
            WeeklyVolumeRow(
                week_start=ws,
                week_label=label,
                strength_sessions=len(strength_sess),
                run_count=len(runs),
                run_km=run_km,
                run_minutes=run_min,
            )
        )
    return out


def _recent_activities(db: DbSession, day: date_cls, limit: int = 5) -> list[RecentActivity]:
    rows = (
        db.execute(
            select(GarminActivity)
            .where(GarminActivity.date <= day)
            .order_by(GarminActivity.date.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        RecentActivity(
            activity_id=r.activity_id,
            date=r.date,
            sport_type=r.sport_type,
            duration_min=round(r.duration_s / 60) if r.duration_s else None,
            distance_km=r.distance_km,
            hr_avg=r.hr_avg,
        )
        for r in rows
    ]


# ─── Endpoint ─────────────────────────────────────────────────────────────────


_vo2_cache: dict[str, VO2MaxCard | None] = {}
_vo2_cache_at: dict[str, datetime] = {}


def _latest_vo2_max() -> VO2MaxCard | None:
    """1h cached fetch — Garmin updates this slowly so we avoid hitting it per request."""
    now = datetime.now(UTC)
    cached_at = _vo2_cache_at.get("v")
    if cached_at and (now - cached_at).total_seconds() < 3600:
        return _vo2_cache.get("v")
    try:
        result = garmin_adapter.fetch_latest_vo2_max()
    except GarminAuthError:
        return _vo2_cache.get("v")
    except Exception:
        return _vo2_cache.get("v")
    card = (
        VO2MaxCard(value=round(result.vo2_max, 1), measured_at=result.date)
        if result
        else None
    )
    _vo2_cache["v"] = card
    _vo2_cache_at["v"] = now
    return card


@router.get("", response_model=DashboardResponse)
def dashboard(db: Db) -> DashboardResponse:
    today = datetime.now(UTC).date()
    return DashboardResponse(
        today=_today_card(db, today),
        trend=_trend(db, today, days=7),
        body_battery_intraday=_body_battery_intraday(db, today, days=7),
        weekly_volume=_weekly_volume(db, today, weeks=4),
        recent_activities=_recent_activities(db, today, limit=5),
        vo2_max=_latest_vo2_max(),
    )
