from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claude_coach.db.base import Base
from claude_coach.db.models import GarminActivity, Session as SessionRow
from claude_coach.services import activity_match
from claude_coach.services.sessions import (
    SessionCreate,
    SetInput,
    create_session,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def test_create_session_writes_sets_and_derived_1rm(db):
    payload = SessionCreate(
        plan_slug="test-plan",
        workout_template_id="A",
        date=date(2026, 5, 20),
        sets=[
            SetInput(
                block_idx=0,
                exercise_id="bench_press",
                set_idx=1,
                planned_reps=10,
                actual_reps=10,
                actual_weight_kg=80.0,
            ),
            SetInput(
                block_idx=0,
                exercise_id="bench_press",
                set_idx=2,
                planned_reps=10,
                actual_reps=8,
                actual_weight_kg=85.0,
            ),
            SetInput(
                block_idx=0,
                exercise_id="bench_press",
                set_idx=3,
                planned_reps=10,
                actual_reps=10,
                actual_weight_kg=12.0,
                is_warmup=True,
            ),
        ],
    )
    result = create_session(db, payload)
    assert result.id > 0

    row = db.get(SessionRow, result.id)
    assert row is not None
    assert len(row.sets) == 3

    # Epley best across non-warmup sets: 85*(1+8/30)=85*1.2667=107.67
    # vs 80*(1+10/30)=106.67 → set 2 wins.
    assert len(result.derived_1rm) == 1
    rec = result.derived_1rm[0]
    assert rec["exercise_id"] == "bench_press"
    assert rec["weight_kg"] == 85.0
    assert rec["reps"] == 8
    assert round(rec["estimated_1rm"], 2) == round(85 * (1 + 8 / 30), 2)


def test_auto_match_picks_run_over_strength_for_run_session(db):
    db.add_all(
        [
            GarminActivity(
                activity_id=1,
                date=date(2026, 5, 20),
                sport_type="running",
                duration_s=2400,
            ),
            GarminActivity(
                activity_id=2,
                date=date(2026, 5, 20),
                sport_type="strength_training",
                duration_s=3600,
            ),
        ]
    )
    db.commit()

    row = SessionRow(
        plan_slug="p",
        workout_template_id="run-1",
        date=date(2026, 5, 20),
        status="done",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    linked = activity_match.auto_link(db, row, session_kind="run")
    assert linked == 1
    assert row.activity_link_source == "auto"


def test_auto_match_skips_activity_already_linked(db):
    db.add(
        GarminActivity(
            activity_id=10,
            date=date(2026, 5, 20),
            sport_type="running",
            duration_s=1800,
        )
    )
    existing = SessionRow(
        plan_slug="p",
        workout_template_id="run-1",
        date=date(2026, 5, 20),
        status="done",
        garmin_activity_id=10,
        activity_link_source="manual",
    )
    db.add(existing)
    db.commit()

    new_row = SessionRow(
        plan_slug="p",
        workout_template_id="run-1",
        date=date(2026, 5, 20),
        status="done",
    )
    db.add(new_row)
    db.commit()
    db.refresh(new_row)

    linked = activity_match.auto_link(db, new_row, session_kind="run")
    assert linked is None
    assert new_row.activity_link_source == "none"


def test_manual_relink_and_unlink(db):
    db.add(
        GarminActivity(
            activity_id=77, date=date(2026, 5, 20), sport_type="running", duration_s=1200
        )
    )
    row = SessionRow(
        plan_slug="p",
        workout_template_id="A",
        date=date(2026, 5, 20),
        status="done",
    )
    db.add(row)
    db.commit()

    activity_match.set_link(db, row, 77)
    assert row.garmin_activity_id == 77
    assert row.activity_link_source == "manual"

    activity_match.set_link(db, row, None)
    assert row.garmin_activity_id is None
    assert row.activity_link_source == "none"
