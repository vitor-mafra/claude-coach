from __future__ import annotations

from datetime import date as date_cls, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from claude_coach.adapters.email import EmailError, adapter as email_adapter, markdown_to_html
from claude_coach.api.security import rate_limit_expensive
from claude_coach.db.models import Insight
from claude_coach.db.session import get_db
from claude_coach.services.weekly_report import service as report_service

router = APIRouter(prefix="/reports", tags=["reports"])

Db = Annotated[DbSession, Depends(get_db)]


class ReportResponse(BaseModel):
    id: int
    week_start: date_cls | None
    week_end: date_cls | None
    generated_at: datetime
    content_md: str
    llm_provider: str | None
    llm_model: str | None
    context: dict[str, Any] | None = None


class ReportListItem(BaseModel):
    id: int
    week_start: date_cls | None
    week_end: date_cls | None
    generated_at: datetime
    llm_model: str | None


def _to_response(row: Insight, with_context: bool = True) -> ReportResponse:
    return ReportResponse(
        id=row.id,
        week_start=row.week_start,
        week_end=row.week_end,
        generated_at=row.generated_at,
        content_md=row.content_md,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        context=row.context_payload if with_context else None,
    )


@router.post(
    "/generate",
    response_model=ReportResponse,
    dependencies=[Depends(rate_limit_expensive("weekly_report"))],
)
def generate(
    db: Db,
    week_start: date_cls | None = Query(default=None),
    week_end: date_cls | None = Query(default=None),
    send_email: bool = Query(default=False),
) -> ReportResponse:
    result = report_service.generate(db, week_start=week_start, week_end=week_end)
    row = db.get(Insight, result.id)
    assert row is not None

    if send_email:
        try:
            email_adapter.send(
                subject=f"Claude Coach — relatório {result.week_start} a {result.week_end}",
                html=markdown_to_html(result.content_md),
            )
        except EmailError as exc:
            raise HTTPException(502, f"email failed: {exc}") from exc

    return _to_response(row)


@router.get("", response_model=list[ReportListItem])
def list_reports(db: Db, limit: int = Query(default=20, ge=1, le=100)) -> list[ReportListItem]:
    rows = (
        db.execute(
            select(Insight)
            .where(Insight.type == "weekly_report")
            .order_by(Insight.generated_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        ReportListItem(
            id=r.id,
            week_start=r.week_start,
            week_end=r.week_end,
            generated_at=r.generated_at,
            llm_model=r.llm_model,
        )
        for r in rows
    ]


@router.get("/{report_id}", response_model=ReportResponse)
def get_report(report_id: int, db: Db) -> ReportResponse:
    row = db.get(Insight, report_id)
    if not row or row.type != "weekly_report":
        raise HTTPException(404, f"report {report_id} not found")
    return _to_response(row)


@router.delete("/{report_id}", status_code=204)
def delete_report(report_id: int, db: Db) -> None:
    row = db.get(Insight, report_id)
    if not row or row.type != "weekly_report":
        raise HTTPException(404, f"report {report_id} not found")
    db.delete(row)
    db.commit()
