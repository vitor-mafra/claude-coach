"""SQLAlchemy models. Observability + Garmin time-series. Sessions/sets land in Phase 4."""

from datetime import UTC, date as date_cls, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from claude_coach.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="garmin")
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    status: Mapped[str] = mapped_column(String(16))
    items_pulled: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class DailyMetric(Base):
    __tablename__ = "daily_metrics"

    date: Mapped[date_cls] = mapped_column(Date, primary_key=True)
    sleep_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_battery_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_battery_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stress_avg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hrv_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_readiness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid_as_of_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class GarminActivity(Base):
    __tablename__ = "garmin_activities"

    activity_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    date: Mapped[date_cls] = mapped_column(Date, index=True)
    sport_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr_avg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hr_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    training_effect_aerobic: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_effect_anaerobic: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_slug: Mapped[str] = mapped_column(String(128), index=True)
    workout_template_id: Mapped[str] = mapped_column(String(32))
    date: Mapped[date_cls] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(16), default="done")  # planned/done/skipped
    garmin_activity_id: Mapped[int | None] = mapped_column(
        ForeignKey("garmin_activities.activity_id"), nullable=True, index=True
    )
    activity_link_source: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )  # auto/manual/none
    note: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    sets: Mapped[list["SessionSet"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionSet.block_idx, SessionSet.set_idx",
    )


class SessionSet(Base):
    __tablename__ = "session_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    block_idx: Mapped[int] = mapped_column(Integer)
    exercise_id: Mapped[str] = mapped_column(String(128), index=True)
    set_idx: Mapped[int] = mapped_column(Integer)
    planned_reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_reps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_warmup: Mapped[bool] = mapped_column(Boolean, default=False)
    is_dropset_continuation: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    session: Mapped[Session] = relationship(back_populates="sets")


class Tested1RM(Base):
    __tablename__ = "tested_1rm"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exercise_id: Mapped[str] = mapped_column(String(128), index=True)
    date: Mapped[date_cls] = mapped_column(Date, index=True)
    weight_kg: Mapped[float] = mapped_column(Float)
    reps_done: Mapped[int] = mapped_column(Integer)
    estimated_1rm: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16), default="derived")  # test/derived
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)  # briefing | weekly_report
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    target_date: Mapped[date_cls | None] = mapped_column(Date, nullable=True, index=True)
    week_start: Mapped[date_cls | None] = mapped_column(Date, nullable=True)
    week_end: Mapped[date_cls | None] = mapped_column(Date, nullable=True)
    content_md: Mapped[str] = mapped_column(String, default="")
    llm_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_context_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    context_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class BodyMetric(Base):
    __tablename__ = "body_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date_cls] = mapped_column(Date, index=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    lean_mass_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="garmin")
