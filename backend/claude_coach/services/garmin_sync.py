"""GarminSyncService — orchestrates GarminAdapter fetches and UPSERTs into
daily_metrics / garmin_activities / body_metrics. Logs the run in sync_runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date as date_cls, datetime, timedelta

import structlog
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from claude_coach.adapters.garmin import GarminAdapter, adapter as default_adapter
from claude_coach.db.models import BodyMetric, DailyMetric, GarminActivity, SyncRun

log = structlog.get_logger(__name__)


@dataclass
class SyncResult:
    date: date_cls
    activities: int
    daily: bool
    body: bool
    status: str
    error: str | None = None


class GarminSyncService:
    def __init__(self, adapter: GarminAdapter | None = None) -> None:
        self._adapter = adapter or default_adapter

    def sync_day(self, db: Session, day: date_cls | None = None) -> SyncResult:
        target = day or (datetime.now(UTC).date() - timedelta(days=1))
        items_pulled = 0
        try:
            activities = self._adapter.fetch_activities(target)
            for act in activities:
                stmt = sqlite_insert(GarminActivity).values(
                    activity_id=act.activity_id,
                    date=act.date,
                    sport_type=act.sport_type,
                    duration_s=act.duration_s,
                    distance_km=act.distance_km,
                    hr_avg=act.hr_avg,
                    hr_max=act.hr_max,
                    training_effect_aerobic=act.training_effect_aerobic,
                    training_effect_anaerobic=act.training_effect_anaerobic,
                    raw_payload=act.raw,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["activity_id"],
                    set_={
                        "date": stmt.excluded.date,
                        "sport_type": stmt.excluded.sport_type,
                        "duration_s": stmt.excluded.duration_s,
                        "distance_km": stmt.excluded.distance_km,
                        "hr_avg": stmt.excluded.hr_avg,
                        "hr_max": stmt.excluded.hr_max,
                        "training_effect_aerobic": stmt.excluded.training_effect_aerobic,
                        "training_effect_anaerobic": stmt.excluded.training_effect_anaerobic,
                        "raw_payload": stmt.excluded.raw_payload,
                    },
                )
                db.execute(stmt)
            items_pulled += len(activities)

            daily = self._adapter.fetch_daily(target)
            stmt = sqlite_insert(DailyMetric).values(
                date=daily.date,
                sleep_score=daily.sleep_score,
                sleep_duration_min=daily.sleep_duration_min,
                body_battery_start=daily.body_battery_start,
                body_battery_end=daily.body_battery_end,
                stress_avg=daily.stress_avg,
                hrv_avg=daily.hrv_avg,
                training_readiness=daily.training_readiness,
                weight_kg=None,
                valid_as_of_timestamp=daily.valid_as_of_timestamp,
                raw_payload=daily.raw,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["date"],
                set_={
                    "sleep_score": stmt.excluded.sleep_score,
                    "sleep_duration_min": stmt.excluded.sleep_duration_min,
                    "body_battery_start": stmt.excluded.body_battery_start,
                    "body_battery_end": stmt.excluded.body_battery_end,
                    "stress_avg": stmt.excluded.stress_avg,
                    "hrv_avg": stmt.excluded.hrv_avg,
                    "training_readiness": stmt.excluded.training_readiness,
                    "valid_as_of_timestamp": stmt.excluded.valid_as_of_timestamp,
                    "raw_payload": stmt.excluded.raw_payload,
                },
            )
            db.execute(stmt)
            items_pulled += 1

            weight = self._adapter.fetch_weight(target)
            body_synced = False
            if weight and weight.weight_kg is not None:
                # idempotent on (date, source=garmin): delete-then-insert keeps it simple
                db.query(BodyMetric).filter(
                    BodyMetric.date == weight.date, BodyMetric.source == "garmin"
                ).delete()
                db.add(
                    BodyMetric(
                        date=weight.date,
                        weight_kg=weight.weight_kg,
                        body_fat_pct=weight.body_fat_pct,
                        lean_mass_kg=weight.lean_mass_kg,
                        source="garmin",
                    )
                )
                # mirror into daily_metrics.weight_kg
                db.execute(
                    sqlite_insert(DailyMetric)
                    .values(date=weight.date, weight_kg=weight.weight_kg)
                    .on_conflict_do_update(
                        index_elements=["date"],
                        set_={"weight_kg": weight.weight_kg},
                    )
                )
                items_pulled += 1
                body_synced = True

            run = SyncRun(source="garmin", status="ok", items_pulled=items_pulled)
            db.add(run)
            db.commit()
            log.info("garmin.sync.ok", date=str(target), items=items_pulled)
            return SyncResult(
                date=target,
                activities=len(activities),
                daily=True,
                body=body_synced,
                status="ok",
            )
        except Exception as exc:
            db.rollback()
            run = SyncRun(
                source="garmin",
                status="error",
                items_pulled=items_pulled,
                error=str(exc)[:1000],
            )
            db.add(run)
            db.commit()
            log.error("garmin.sync.fail", date=str(target), error=str(exc))
            return SyncResult(
                date=target,
                activities=0,
                daily=False,
                body=False,
                status="error",
                error=str(exc),
            )


service = GarminSyncService()
