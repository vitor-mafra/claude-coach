"""Sync service with a stub adapter: idempotent UPSERT into garmin tables."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from claude_coach.adapters.garmin import FetchedActivity, FetchedDaily, FetchedWeight
from claude_coach.db.base import Base
from claude_coach.db.models import BodyMetric, DailyMetric, GarminActivity, SyncRun
from claude_coach.services.garmin_sync import GarminSyncService


class StubAdapter:
    def __init__(self, day: date) -> None:
        self.day = day
        self.calls = 0

    def fetch_activities(self, day: date) -> list[FetchedActivity]:
        self.calls += 1
        return [
            FetchedActivity(
                activity_id=42,
                date=day,
                sport_type="running",
                duration_s=1800,
                distance_km=5.2,
                hr_avg=155,
                hr_max=178,
                training_effect_aerobic=3.1,
                training_effect_anaerobic=0.6,
                raw={"id": 42},
            )
        ]

    def fetch_daily(self, day: date) -> FetchedDaily:
        return FetchedDaily(
            date=day,
            sleep_score=82,
            sleep_duration_min=420,
            body_battery_start=75,
            body_battery_end=30,
            stress_avg=27,
            hrv_avg=58.4,
            training_readiness=68,
            valid_as_of_timestamp=datetime(2026, 5, 20, 7, 0, tzinfo=UTC),
            raw={"src": "stub"},
        )

    def fetch_weight(self, day: date) -> FetchedWeight | None:
        return FetchedWeight(date=day, weight_kg=72.4, body_fat_pct=15.1, lean_mass_kg=33.0)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def test_sync_inserts_then_upserts_idempotently(db_session):
    target = date(2026, 5, 20)
    svc = GarminSyncService(adapter=StubAdapter(target))

    r1 = svc.sync_day(db_session, day=target)
    assert r1.status == "ok"
    assert r1.activities == 1
    assert r1.daily is True
    assert r1.body is True

    r2 = svc.sync_day(db_session, day=target)
    assert r2.status == "ok"

    activities = db_session.execute(select(GarminActivity)).scalars().all()
    assert len(activities) == 1
    assert activities[0].activity_id == 42
    assert activities[0].distance_km == 5.2

    daily = db_session.execute(select(DailyMetric)).scalars().all()
    assert len(daily) == 1
    assert daily[0].sleep_score == 82
    assert daily[0].weight_kg == 72.4

    body = db_session.execute(select(BodyMetric)).scalars().all()
    assert len(body) == 1
    assert body[0].weight_kg == 72.4

    runs = db_session.execute(select(SyncRun)).scalars().all()
    assert len(runs) == 2
    assert all(r.status == "ok" for r in runs)


def test_sync_error_records_failed_run(db_session):
    class FailingAdapter(StubAdapter):
        def fetch_activities(self, day: date):
            raise RuntimeError("garmin down")

    svc = GarminSyncService(adapter=FailingAdapter(date(2026, 5, 20)))
    result = svc.sync_day(db_session, day=date(2026, 5, 20))
    assert result.status == "error"
    assert "garmin down" in (result.error or "")

    runs = db_session.execute(select(SyncRun)).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == "error"
