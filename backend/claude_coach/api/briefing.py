from __future__ import annotations

from datetime import date as date_cls, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from claude_coach.db.models import Insight
from claude_coach.db.session import get_db
from claude_coach.services.briefing import service as briefing_service

router = APIRouter(prefix="/briefing", tags=["briefing"])

Db = Annotated[DbSession, Depends(get_db)]


class BriefingResponse(BaseModel):
    id: int
    target_date: date_cls
    content_md: str
    generated_at: datetime
    llm_provider: str | None
    llm_model: str | None
    context: dict[str, Any] | None = None


class BriefingListItem(BaseModel):
    id: int
    target_date: date_cls | None
    generated_at: datetime
    llm_provider: str | None
    llm_model: str | None


def _to_response(row: Insight, include_context: bool = True) -> BriefingResponse:
    return BriefingResponse(
        id=row.id,
        target_date=row.target_date,  # type: ignore[arg-type]
        content_md=row.content_md,
        generated_at=row.generated_at,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        context=row.context_payload if include_context else None,
    )


@router.post("/today", response_model=BriefingResponse)
def generate(
    db: Db,
    date: date_cls | None = Query(default=None, description="defaults to today"),
    refresh_garmin: bool = Query(default=True),
) -> BriefingResponse:
    result = briefing_service.generate(db, day=date, refresh_garmin=refresh_garmin)
    if result is None:
        raise HTTPException(404, "no active plan; import one first")
    row = db.get(Insight, result.id)
    assert row is not None
    return _to_response(row)


@router.get("", response_model=list[BriefingListItem])
def list_briefings(db: Db, limit: int = Query(default=20, ge=1, le=100)) -> list[BriefingListItem]:
    rows = (
        db.execute(
            select(Insight)
            .where(Insight.type == "briefing")
            .order_by(Insight.generated_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        BriefingListItem(
            id=r.id,
            target_date=r.target_date,
            generated_at=r.generated_at,
            llm_provider=r.llm_provider,
            llm_model=r.llm_model,
        )
        for r in rows
    ]


@router.get("/{briefing_id}", response_model=BriefingResponse)
def get_briefing(briefing_id: int, db: Db) -> BriefingResponse:
    row = db.get(Insight, briefing_id)
    if not row or row.type != "briefing":
        raise HTTPException(404, f"briefing {briefing_id} not found")
    return _to_response(row)
