"""Persist every LLM call into the `llm_calls` table.

Best-effort: a failure here must not break the LLM call itself, so DB exceptions
are swallowed and logged. The router calls `record_call` after every completion.
"""

from __future__ import annotations

import logging

from claude_coach.adapters.llm.base import LLMResult
from claude_coach.adapters.llm.pricing import estimate_cost_usd
from claude_coach.db.models import LLMCall
from claude_coach.db.session import SessionLocal

log = logging.getLogger(__name__)


def record_call(
    task_id: str,
    result: LLMResult,
    success: bool = True,
    error: str | None = None,
) -> None:
    cost = estimate_cost_usd(
        result.provider, result.model, result.input_tokens, result.output_tokens
    )
    try:
        with SessionLocal() as session:
            session.add(
                LLMCall(
                    task_id=task_id,
                    provider=result.provider,
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_usd_estimate=cost,
                    duration_ms=result.duration_ms,
                    success=success,
                    error=error,
                )
            )
            session.commit()
    except Exception as exc:  # pragma: no cover -- defensive, never break the call
        log.warning("failed to log llm call (task=%s): %s", task_id, exc)


def record_failure(task_id: str, provider: str, model: str, error: str) -> None:
    """Log an LLM call that failed before producing any tokens."""
    try:
        with SessionLocal() as session:
            session.add(
                LLMCall(
                    task_id=task_id,
                    provider=provider,
                    model=model,
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd_estimate=None,
                    duration_ms=0,
                    success=False,
                    error=error,
                )
            )
            session.commit()
    except Exception as exc:  # pragma: no cover
        log.warning("failed to log llm failure (task=%s): %s", task_id, exc)
