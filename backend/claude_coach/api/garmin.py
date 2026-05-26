from datetime import date as date_cls, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from claude_coach.adapters.garmin import GarminAuthError
from claude_coach.db.models import DailyMetric, GarminActivity, SyncRun
from claude_coach.db.session import get_db
from claude_coach.services.garmin_sync import service as sync_service

router = APIRouter(prefix="/garmin", tags=["garmin"])

DbSession = Annotated[Session, Depends(get_db)]


class SyncResponse(BaseModel):
    date: date_cls
    activities: int
    daily: bool
    body: bool
    status: str
    error: str | None = None


class SyncRunRow(BaseModel):
    id: int
    source: str
    ran_at: datetime
    status: str
    items_pulled: int
    error: str | None


class DailyMetricRow(BaseModel):
    date: date_cls
    sleep_score: int | None
    sleep_duration_min: int | None
    body_battery_start: int | None
    body_battery_end: int | None
    stress_avg: int | None
    hrv_avg: float | None
    training_readiness: int | None
    weight_kg: float | None


class ActivityRow(BaseModel):
    activity_id: int
    date: date_cls
    sport_type: str | None
    duration_s: int | None
    distance_km: float | None
    hr_avg: int | None
    hr_max: int | None
    training_effect_aerobic: float | None
    training_effect_anaerobic: float | None


class HRZonesResponse(BaseModel):
    training_method: str
    max_hr: int
    resting_hr: int | None = None
    lactate_threshold_hr: int | None = None
    zone_floors: dict[str, int]  # {"Z1": 103, ...}
    zone_bounds: dict[str, tuple[int, int]]  # {"Z1": (103, 123), ...}


@router.get("/hr-zones", response_model=HRZonesResponse)
def hr_zones(sync_profile: bool = Query(default=True)) -> HRZonesResponse:
    """Read user's HR zones from Garmin. Side-effect: if `sync_profile`, updates
    the profile's `fc_max_bpm` to Garmin's value and marks source='garmin'."""
    from claude_coach.adapters.garmin import adapter as garmin_adapter
    from claude_coach.domain.calculations import hr_zone_bounds_from_floors
    from claude_coach.services.profile import load_profile, save_profile

    try:
        z = garmin_adapter.fetch_hr_zones()
    except GarminAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if not z:
        raise HTTPException(404, "Garmin did not return HR zones for the user")

    bounds = {
        zone: hr_zone_bounds_from_floors(z.zone_floors, z.max_hr, zone)
        for zone in z.zone_floors
    }

    if sync_profile:
        profile = load_profile()
        if profile and (
            profile.fc_max_bpm != z.max_hr or profile.fc_max_source != "garmin"
        ):
            profile.fc_max_bpm = z.max_hr
            profile.fc_max_source = "garmin"
            save_profile(profile)

    return HRZonesResponse(
        training_method=z.training_method,
        max_hr=z.max_hr,
        resting_hr=z.resting_hr,
        lactate_threshold_hr=z.lactate_threshold_hr,
        zone_floors=z.zone_floors,
        zone_bounds=bounds,
    )


@router.post("/sync", response_model=SyncResponse)
def sync(
    db: DbSession,
    date: date_cls | None = Query(default=None, description="defaults to yesterday"),
) -> SyncResponse:
    try:
        result = sync_service.sync_day(db, day=date)
    except GarminAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return SyncResponse(**result.__dict__)


@router.get("/runs", response_model=list[SyncRunRow])
def runs(db: DbSession, limit: int = Query(default=20, ge=1, le=200)) -> list[SyncRunRow]:
    rows = db.execute(
        select(SyncRun).order_by(SyncRun.ran_at.desc()).limit(limit)
    ).scalars().all()
    return [
        SyncRunRow(
            id=r.id,
            source=r.source,
            ran_at=r.ran_at,
            status=r.status,
            items_pulled=r.items_pulled,
            error=r.error,
        )
        for r in rows
    ]


@router.get("/daily", response_model=list[DailyMetricRow])
def daily(
    db: DbSession,
    start: date_cls | None = Query(default=None),
    end: date_cls | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=365),
) -> list[DailyMetricRow]:
    stmt = select(DailyMetric)
    if start:
        stmt = stmt.where(DailyMetric.date >= start)
    if end:
        stmt = stmt.where(DailyMetric.date <= end)
    stmt = stmt.order_by(DailyMetric.date.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [
        DailyMetricRow(
            date=r.date,
            sleep_score=r.sleep_score,
            sleep_duration_min=r.sleep_duration_min,
            body_battery_start=r.body_battery_start,
            body_battery_end=r.body_battery_end,
            stress_avg=r.stress_avg,
            hrv_avg=r.hrv_avg,
            training_readiness=r.training_readiness,
            weight_kg=r.weight_kg,
        )
        for r in rows
    ]


@router.get("/activities", response_model=list[ActivityRow])
def activities(
    db: DbSession,
    start: date_cls | None = Query(default=None),
    end: date_cls | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[ActivityRow]:
    stmt = select(GarminActivity)
    if start:
        stmt = stmt.where(GarminActivity.date >= start)
    if end:
        stmt = stmt.where(GarminActivity.date <= end)
    stmt = stmt.order_by(GarminActivity.date.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [
        ActivityRow(
            activity_id=r.activity_id,
            date=r.date,
            sport_type=r.sport_type,
            duration_s=r.duration_s,
            distance_km=r.distance_km,
            hr_avg=r.hr_avg,
            hr_max=r.hr_max,
            training_effect_aerobic=r.training_effect_aerobic,
            training_effect_anaerobic=r.training_effect_anaerobic,
        )
        for r in rows
    ]
