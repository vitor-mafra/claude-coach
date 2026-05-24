"""Match a logged Session with a Garmin activity from the same date.

Heuristic (single-user, low volume):
- Same `date`.
- Sport family compatible with the session kind (strength vs run).
- If multiple candidates: pick the longest by `duration_s`.
- Skip activities already linked to another session.

The link is set as `Session.garmin_activity_id` with
`activity_link_source = "auto"`. A manual relink stamps "manual"; the user can
also unlink (sets both fields to None / "none").
"""

from __future__ import annotations

from datetime import date as date_cls

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from claude_coach.db.models import GarminActivity, Session as SessionRow

log = structlog.get_logger(__name__)

_RUN_SPORTS = {"running", "trail_running", "treadmill_running", "track_running", "indoor_running"}
_STRENGTH_SPORTS = {
    "strength_training",
    "indoor_cardio",
    "fitness_equipment",
    "other",
}


def _sport_matches(session_kind: str, sport: str | None) -> bool:
    if not sport:
        return False
    sport = sport.lower()
    if session_kind == "run":
        return sport in _RUN_SPORTS or "run" in sport
    if session_kind == "strength":
        return sport in _STRENGTH_SPORTS or "strength" in sport
    return False


def find_candidate(
    db: DbSession, day: date_cls, session_kind: str, exclude_session_id: int | None = None
) -> GarminActivity | None:
    rows = db.execute(
        select(GarminActivity).where(GarminActivity.date == day)
    ).scalars().all()
    if not rows:
        return None
    linked_ids = set(
        db.execute(
            select(SessionRow.garmin_activity_id).where(
                SessionRow.garmin_activity_id.is_not(None),
                SessionRow.id != (exclude_session_id or -1),
            )
        )
        .scalars()
        .all()
    )
    candidates = [
        a for a in rows if _sport_matches(session_kind, a.sport_type) and a.activity_id not in linked_ids
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a.duration_s or 0), reverse=True)
    return candidates[0]


def auto_link(db: DbSession, session_row: SessionRow, session_kind: str) -> int | None:
    """Set garmin_activity_id if not yet linked. Returns activity_id if linked."""
    if session_row.garmin_activity_id is not None:
        return session_row.garmin_activity_id
    activity = find_candidate(db, session_row.date, session_kind, exclude_session_id=session_row.id)
    if not activity:
        session_row.activity_link_source = "none"
        return None
    session_row.garmin_activity_id = activity.activity_id
    session_row.activity_link_source = "auto"
    log.info(
        "session.activity.auto_linked",
        session_id=session_row.id,
        activity_id=activity.activity_id,
        sport=activity.sport_type,
    )
    return activity.activity_id


def set_link(
    db: DbSession, session_row: SessionRow, activity_id: int | None
) -> None:
    if activity_id is None:
        session_row.garmin_activity_id = None
        session_row.activity_link_source = "none"
        return
    activity = db.get(GarminActivity, activity_id)
    if activity is None:
        raise ValueError(f"garmin activity {activity_id} not found")
    session_row.garmin_activity_id = activity_id
    session_row.activity_link_source = "manual"
