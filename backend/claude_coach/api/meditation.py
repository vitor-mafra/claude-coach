"""Meditation / mindfulness tracking.

A separate wellness track from training: it shows up on the calendar but does
NOT count toward the day's training target.

The create endpoint doubles as a generic ingest: a future automation (Tasker,
a Google Fit poller, etc.) can POST here with a `source` and an `external_id`
for idempotency. Manual entries from the app omit `external_id`.
"""

from __future__ import annotations

from datetime import date as date_cls
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from claude_coach.db.models import MeditationSession
from claude_coach.db.session import get_db

router = APIRouter(prefix="/meditation", tags=["meditation"])

Db = Annotated[DbSession, Depends(get_db)]


class MeditationCreate(BaseModel):
    date: date_cls
    duration_min: int | None = Field(default=None, ge=0, le=24 * 60)
    source: str = "manual"
    note: str | None = None
    external_id: str | None = None


class MeditationOut(BaseModel):
    id: int
    date: date_cls
    duration_min: int | None
    source: str
    note: str | None


def _to_out(row: MeditationSession) -> MeditationOut:
    return MeditationOut(
        id=row.id,
        date=row.date,
        duration_min=row.duration_min,
        source=row.source,
        note=row.note,
    )


@router.post("", response_model=MeditationOut, status_code=201)
def create_meditation(payload: MeditationCreate, db: Db) -> MeditationOut:
    # Idempotent on external_id so an automated ingest can safely retry.
    if payload.external_id:
        existing = db.execute(
            select(MeditationSession).where(
                MeditationSession.external_id == payload.external_id
            )
        ).scalar_one_or_none()
        if existing:
            return _to_out(existing)

    row = MeditationSession(
        date=payload.date,
        duration_min=payload.duration_min,
        source=payload.source or "manual",
        note=payload.note,
        external_id=payload.external_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.get("", response_model=list[MeditationOut])
def list_meditation(
    db: Db,
    start: date_cls | None = Query(default=None),
    end: date_cls | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[MeditationOut]:
    stmt = select(MeditationSession)
    if start:
        stmt = stmt.where(MeditationSession.date >= start)
    if end:
        stmt = stmt.where(MeditationSession.date <= end)
    stmt = stmt.order_by(MeditationSession.date.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [_to_out(r) for r in rows]


@router.delete("/{meditation_id}", status_code=204)
def delete_meditation(meditation_id: int, db: Db) -> None:
    row = db.get(MeditationSession, meditation_id)
    if not row:
        raise HTTPException(404, f"meditation {meditation_id} not found")
    db.delete(row)
    db.commit()
