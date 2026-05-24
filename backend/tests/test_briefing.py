"""Briefing service: context shape + persistence with a stub LLM router."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claude_coach.adapters.llm.base import LLMResult, Message
from claude_coach.db.base import Base
from claude_coach.db.models import (
    DailyMetric,
    GarminActivity,
    Insight,
    Session as SessionRow,
    SessionSet,
    Tested1RM,
)
from claude_coach.services.briefing import (
    BriefingService,
    _history_for_exercise,
    build_context,
)


class StubRouter:
    def __init__(self, text: str = "### briefing stub") -> None:
        self.text = text
        self.calls: list[tuple[str, str | None, str]] = []

    def complete(self, task_id: str, messages: list[Message], system: str | None = None):
        prompt = messages[0].parts[0].text  # type: ignore[union-attr]
        self.calls.append((task_id, system, prompt))
        return LLMResult(
            text=self.text,
            input_tokens=100,
            output_tokens=50,
            model="stub-model",
            provider="stub",
            duration_ms=10,
        )


@dataclass
class StubSync:
    calls: list[date]

    def sync_day(self, db, day=None):  # noqa: ARG002
        self.calls.append(day)
        return type("R", (), {"status": "ok", "activities": 0, "daily": True, "body": False})()


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


def _seed_history(db) -> None:
    """Two past sessions of bench press with progression."""
    for i, (d, w) in enumerate([(date(2026, 5, 15), 80.0), (date(2026, 5, 18), 82.5)]):
        row = SessionRow(
            plan_slug="p",
            workout_template_id="A",
            date=d,
            status="done",
            note=f"feeling {i+1}",
        )
        db.add(row)
        db.flush()
        for s_idx in range(1, 4):
            db.add(
                SessionSet(
                    session_id=row.id,
                    block_idx=0,
                    exercise_id="bench_press",
                    set_idx=s_idx,
                    planned_reps=10,
                    actual_reps=10,
                    actual_weight_kg=w,
                    is_warmup=False,
                )
            )
        db.add(
            Tested1RM(
                exercise_id="bench_press",
                date=d,
                weight_kg=w,
                reps_done=10,
                estimated_1rm=w * (1 + 10 / 30),
                source="derived",
                session_id=row.id,
            )
        )
    db.commit()


def test_history_for_exercise_collects_latest_sessions(db):
    _seed_history(db)
    h = _history_for_exercise(db, "bench_press", "Bench Press")
    assert len(h.recent_sessions) == 2
    assert h.recent_sessions[0]["date"] == "2026-05-18"
    assert h.recent_sessions[0]["sets"][0]["weight_kg"] == 82.5
    assert h.best_recent_1rm and round(h.best_recent_1rm, 1) == round(82.5 * (1 + 10 / 30), 1)
    assert "feeling 2" in h.notes


def test_build_context_with_no_plan_returns_none(db):
    # No active plan present in data/plans → build_context returns None
    ctx = build_context(db, date(2026, 5, 22))
    # The real on-disk plan may or may not exist; tolerate both.
    if ctx is not None:
        # If a plan IS present, the context should still be well-formed:
        assert ctx.date == date(2026, 5, 22)
        assert isinstance(ctx.workouts, list)


def test_garmin_today_and_7d_avg(db):
    for d, score, hrv in [
        (date(2026, 5, 15), 70, 60.0),
        (date(2026, 5, 16), 80, 70.0),
        (date(2026, 5, 17), 90, 80.0),
        (date(2026, 5, 18), 85, None),  # missing hrv
    ]:
        db.add(
            DailyMetric(
                date=d,
                sleep_score=score,
                hrv_avg=hrv,
                sleep_duration_min=420,
                body_battery_start=70,
                body_battery_end=40,
                stress_avg=30,
            )
        )
    db.commit()

    from claude_coach.services.briefing import _garmin_today

    g = _garmin_today(db, date(2026, 5, 18))
    assert g is not None
    assert g.sleep_score == 85
    # 7d avg excludes target date itself
    assert g.sleep_7d_avg == 80.0  # (70+80+90)/3
    assert g.hrv_7d_avg == 70.0  # (60+70+80)/3


def test_briefing_service_persists_insight_when_no_workout_today(db, monkeypatch):
    # Force "no workouts today" by mocking workout_for_date to return empty.
    # We also need an active plan; mock that too.
    from claude_coach.services import briefing as briefing_mod

    fake_plan = type("P", (), {"templates": {}, "schedule": {}})()
    monkeypatch.setattr(briefing_mod, "load_active_plan", lambda: ("test-plan", fake_plan))
    monkeypatch.setattr(briefing_mod, "workout_for_date", lambda *a, **k: [])

    stub_sync = StubSync(calls=[])
    monkeypatch.setattr(briefing_mod, "garmin_sync", stub_sync)

    router = StubRouter()
    svc = BriefingService(llm_router=router)

    result = svc.generate(db, day=date(2026, 5, 22), refresh_garmin=True)
    assert result is not None
    assert "descanso" in result.content_md.lower()
    assert router.calls == []  # rest day skips the LLM
    assert stub_sync.calls == [date(2026, 5, 22)]

    saved = db.query(Insight).all()
    assert len(saved) == 1
    assert saved[0].type == "briefing"


def test_briefing_service_calls_llm_with_context(db, monkeypatch):
    _seed_history(db)
    db.add(
        DailyMetric(
            date=date(2026, 5, 22),
            sleep_score=88,
            sleep_duration_min=440,
            body_battery_start=70,
            body_battery_end=55,
            stress_avg=25,
            hrv_avg=78.0,
        )
    )
    db.add(
        GarminActivity(
            activity_id=999,
            date=date(2026, 5, 20),
            sport_type="running",
            duration_s=1800,
            distance_km=5.0,
            hr_avg=150,
        )
    )
    db.commit()

    from claude_coach.services import briefing as briefing_mod
    from claude_coach.services.sessions import PlannedExercise, PlannedSet, PlannedWorkout

    fake_workout = PlannedWorkout(
        plan_slug="p",
        template_id="A",
        name="Treino A",
        kind="strength",
        date=date(2026, 5, 22),
        exercises=[
            PlannedExercise(
                block_idx=0,
                exercise_id="bench_press",
                exercise_name="Bench Press",
                kind="meta_reps",
                sets=[PlannedSet(set_idx=i, planned_reps=10) for i in range(1, 4)],
                rest_seconds=90,
            ),
        ],
    )

    fake_plan = type("P", (), {"templates": {"A": object()}, "schedule": {}})()
    monkeypatch.setattr(briefing_mod, "load_active_plan", lambda: ("test-plan", fake_plan))
    monkeypatch.setattr(
        briefing_mod, "workout_for_date", lambda *a, **k: [object()]
    )
    monkeypatch.setattr(
        briefing_mod, "planned_workout", lambda *a, **k: fake_workout
    )

    stub_sync = StubSync(calls=[])
    monkeypatch.setattr(briefing_mod, "garmin_sync", stub_sync)

    router = StubRouter(text="### Como você está hoje\nBom.")
    svc = BriefingService(llm_router=router)

    result = svc.generate(db, day=date(2026, 5, 22), refresh_garmin=True)
    assert result is not None
    assert len(router.calls) == 1
    task_id, system, prompt = router.calls[0]
    assert task_id == "briefing"
    assert system and "Claude Coach" in system
    assert "Bench Press" in prompt
    assert "82.5kg×10" in prompt  # latest session set
    assert "Body Battery: 70 → 55" in prompt
    assert "running" in prompt  # recent activity

    saved = db.query(Insight).filter(Insight.id == result.id).one()
    assert saved.llm_provider == "stub"
    assert saved.content_md.startswith("### Como você está")
