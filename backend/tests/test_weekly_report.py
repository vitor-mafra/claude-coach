from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from claude_coach.adapters.email import markdown_to_html
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
from claude_coach.services.weekly_report import (
    WeeklyReportService,
    build_context,
    iso_week_window,
    last_completed_week,
)


class StubRouter:
    def __init__(self, text: str = "## stub report") -> None:
        self.text = text
        self.calls: list[tuple[str, str | None, str]] = []

    def complete(self, task_id: str, messages: list[Message], system: str | None = None):
        prompt = messages[0].parts[0].text  # type: ignore[union-attr]
        self.calls.append((task_id, system, prompt))
        return LLMResult(
            text=self.text,
            input_tokens=200,
            output_tokens=300,
            model="stub-sonnet",
            provider="stub",
            duration_ms=10,
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


def test_iso_week_window_mon_to_sun():
    # 2026-05-22 is a Friday → week Mon 2026-05-18 to Sun 2026-05-24
    ws, we = iso_week_window(date(2026, 5, 22))
    assert ws == date(2026, 5, 18)
    assert we == date(2026, 5, 24)


def test_last_completed_week_excludes_current():
    # If today is Fri 2026-05-22, last completed week is Mon 11 → Sun 17.
    ws, we = last_completed_week(today=date(2026, 5, 22))
    assert ws == date(2026, 5, 11)
    assert we == date(2026, 5, 17)


def _seed_week(db, week_start: date, weight: float, exercise: str = "bench_press") -> None:
    row = SessionRow(
        plan_slug="p",
        workout_template_id="A",
        date=week_start + __import__("datetime").timedelta(days=2),
        status="done",
    )
    db.add(row)
    db.flush()
    for i in range(1, 4):
        db.add(
            SessionSet(
                session_id=row.id,
                block_idx=0,
                exercise_id=exercise,
                set_idx=i,
                planned_reps=10,
                actual_reps=10,
                actual_weight_kg=weight,
                is_warmup=False,
            )
        )
    db.add(
        DailyMetric(
            date=week_start + __import__("datetime").timedelta(days=2),
            sleep_score=80,
            sleep_duration_min=420,
            body_battery_start=70,
            body_battery_end=40,
            stress_avg=25,
            hrv_avg=70.0,
        )
    )
    db.add(
        GarminActivity(
            activity_id=int(weight * 100),
            date=week_start + __import__("datetime").timedelta(days=3),
            sport_type="running",
            duration_s=1800,
            distance_km=5.0,
            hr_avg=150,
        )
    )
    db.commit()


def test_build_context_aggregates_week_and_prev(db):
    this_week = date(2026, 5, 11)
    prev_week = date(2026, 5, 4)
    _seed_week(db, prev_week, weight=80.0)
    _seed_week(db, this_week, weight=82.5)

    ctx = build_context(db, this_week, this_week + __import__("datetime").timedelta(days=6))
    assert ctx.summary.sessions_done == 1
    assert ctx.summary.run_sessions == 1
    assert ctx.summary.run_km_total == 5.0
    assert ctx.prev_summary is not None
    assert ctx.prev_summary.sessions_done == 1

    progressions = {p.exercise_id: p for p in ctx.progressions}
    assert "bench_press" in progressions
    bp = progressions["bench_press"]
    assert bp.last_top == 82.5
    assert bp.prev_week_top == 80.0


def test_service_persists_insight_and_writes_file(tmp_path, monkeypatch, db):
    # Redirect reports dir to a tmp path so we don't touch the real data/ folder.
    from claude_coach.services import weekly_report as wr

    monkeypatch.setattr(wr, "REPORTS_DIR", tmp_path)

    this_week = date(2026, 5, 11)
    _seed_week(db, this_week, weight=80.0)

    router = StubRouter(text="## Resumo\nteste")
    svc = WeeklyReportService(llm_router=router)
    result = svc.generate(
        db,
        week_start=this_week,
        week_end=this_week + __import__("datetime").timedelta(days=6),
    )

    assert result.file_path.exists()
    content = result.file_path.read_text()
    assert "Relatório semanal" in content
    assert "## Resumo" in content

    saved = db.query(Insight).filter(Insight.type == "weekly_report").one()
    assert saved.week_start == this_week
    assert saved.llm_model == "stub-sonnet"

    assert len(router.calls) == 1
    _, system, prompt = router.calls[0]
    assert system and "Claude Coach" in system
    assert "bench_press" in prompt


def test_one_rm_snapshots_include_delta_vs_prior_best(db):
    week_start = date(2026, 5, 11)
    # Prior best 2 weeks back at 80kg
    db.add(
        Tested1RM(
            exercise_id="bench_press",
            date=date(2026, 4, 27),
            weight_kg=80.0,
            reps_done=10,
            estimated_1rm=80 * (1 + 10 / 30),
            source="derived",
        )
    )
    # This week's top at 85kg
    db.add(
        Tested1RM(
            exercise_id="bench_press",
            date=week_start + __import__("datetime").timedelta(days=2),
            weight_kg=85.0,
            reps_done=8,
            estimated_1rm=85 * (1 + 8 / 30),
            source="derived",
        )
    )
    db.commit()

    from claude_coach.services.weekly_report import _one_rm_snapshots

    snaps = _one_rm_snapshots(
        db, week_start, week_start + __import__("datetime").timedelta(days=6)
    )
    assert len(snaps) == 1
    s = snaps[0]
    assert s.exercise_id == "bench_press"
    assert s.week_top_estimated_1rm > s.last_known_estimated_1rm  # type: ignore[operator]
    assert s.delta_vs_last is not None and s.delta_vs_last > 0


def test_generate_dedups_same_week(tmp_path, monkeypatch, db):
    from claude_coach.services import weekly_report as wr

    monkeypatch.setattr(wr, "REPORTS_DIR", tmp_path)
    _seed_week(db, date(2026, 5, 11), weight=80.0)

    router = StubRouter(text="## v1\nx")
    svc = WeeklyReportService(llm_router=router)
    r1 = svc.generate(
        db,
        week_start=date(2026, 5, 11),
        week_end=date(2026, 5, 17),
    )

    router.text = "## v2\ny"
    r2 = svc.generate(
        db,
        week_start=date(2026, 5, 11),
        week_end=date(2026, 5, 17),
    )
    assert r1.id == r2.id  # same insight, updated

    rows = db.query(Insight).filter(Insight.type == "weekly_report").all()
    assert len(rows) == 1
    assert rows[0].content_md.startswith("## v2")


def test_markdown_to_html_handles_headings_bullets_bold():
    md = "## Title\n\n- item **bold**\n- second\n\nparagraph"
    html = markdown_to_html(md)
    assert "<h2 " in html and ">Title</h2>" in html
    assert ">item <strong" in html and "bold</strong></li>" in html
    assert ">second</li>" in html
    assert ">paragraph</p>" in html
    # Footer is appended
    assert "Claude Coach" in html
