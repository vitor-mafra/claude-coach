"""In-process APScheduler. Started/stopped via FastAPI lifespan in main.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from claude_coach.adapters.email import EmailError, adapter as email_adapter, markdown_to_html
from claude_coach.config import settings
from claude_coach.db.session import SessionLocal
from claude_coach.services.garmin_sync import service as garmin_sync
from claude_coach.services.weekly_report import service as weekly_report_service

_WEEKDAY_MAP = {
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}

log = structlog.get_logger(__name__)

_scheduler: BackgroundScheduler | None = None


def _daily_garmin_sync() -> None:
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
    db = SessionLocal()
    try:
        result = garmin_sync.sync_day(db, day=yesterday)
        log.info("scheduler.garmin.sync.done", **result.__dict__)
    finally:
        db.close()


def _weekly_report() -> None:
    db = SessionLocal()
    try:
        result = weekly_report_service.generate(db)
        log.info(
            "scheduler.weekly_report.done",
            id=result.id,
            week_start=str(result.week_start),
            week_end=str(result.week_end),
        )
        if settings.resend_api_key and settings.weekly_report_to_email:
            try:
                email_adapter.send(
                    subject=(
                        f"Claude Coach — relatório {result.week_start} "
                        f"a {result.week_end}"
                    ),
                    html=markdown_to_html(result.content_md),
                )
            except EmailError as exc:
                log.warning("scheduler.weekly_report.email_fail", error=str(exc))
        else:
            log.info("scheduler.weekly_report.email_skipped", reason="resend not configured")
    except Exception as exc:
        log.error("scheduler.weekly_report.fail", error=str(exc))
    finally:
        db.close()


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = BackgroundScheduler(timezone=settings.scheduler_timezone)
    sched.add_job(
        _daily_garmin_sync,
        trigger=CronTrigger(hour=settings.daily_sync_hour, minute=0),
        id="garmin_daily_sync",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    weekly_dow = _WEEKDAY_MAP.get(settings.weekly_report_day.lower(), 0)
    sched.add_job(
        _weekly_report,
        trigger=CronTrigger(
            day_of_week=weekly_dow,
            hour=settings.weekly_report_hour,
            minute=0,
        ),
        id="weekly_report",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    sched.start()
    log.info(
        "scheduler.started",
        tz=settings.scheduler_timezone,
        daily_sync_hour=settings.daily_sync_hour,
        weekly_report_day=settings.weekly_report_day,
        weekly_report_hour=settings.weekly_report_hour,
    )
    _scheduler = sched
    return sched


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
