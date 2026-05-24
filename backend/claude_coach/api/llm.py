"""Read-only LLM observability endpoints."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from claude_coach.db.models import LLMCall
from claude_coach.db.session import get_db

router = APIRouter(prefix="/llm", tags=["llm"])
DbSession = Annotated[Session, Depends(get_db)]


class TaskUsage(BaseModel):
    task_id: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd_estimate: float | None


class UsageSummary(BaseModel):
    range_days: int
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd_estimate: float
    by_task: list[TaskUsage]


@router.get("/usage", response_model=UsageSummary)
def usage(db: DbSession, days: int = 30) -> UsageSummary:
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(
            LLMCall.task_id,
            func.count(LLMCall.id),
            func.coalesce(func.sum(LLMCall.input_tokens), 0),
            func.coalesce(func.sum(LLMCall.output_tokens), 0),
            func.coalesce(func.sum(LLMCall.cost_usd_estimate), 0.0),
        )
        .where(LLMCall.created_at >= since)
        .group_by(LLMCall.task_id)
        .order_by(func.coalesce(func.sum(LLMCall.cost_usd_estimate), 0.0).desc())
    )
    rows = db.execute(stmt).all()

    by_task = [
        TaskUsage(
            task_id=task_id,
            calls=calls,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            cost_usd_estimate=float(cost) if cost else None,
        )
        for (task_id, calls, input_tokens, output_tokens, cost) in rows
    ]
    return UsageSummary(
        range_days=days,
        total_calls=sum(t.calls for t in by_task),
        total_input_tokens=sum(t.input_tokens for t in by_task),
        total_output_tokens=sum(t.output_tokens for t in by_task),
        total_cost_usd_estimate=sum((t.cost_usd_estimate or 0.0) for t in by_task),
        by_task=by_task,
    )
