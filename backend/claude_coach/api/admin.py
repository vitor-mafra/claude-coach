"""Admin / first-run endpoints.

Lets the deployed instance bootstrap itself from the UI:
- Connect Garmin (logs in with env-configured credentials, persists tokens
  to the writable data dir / Railway volume).
- Report system status so the frontend can guide the user through setup.

Plan upload + parse lives in `claude_coach.api.plans` to keep the related
endpoints together.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from claude_coach.adapters.garmin_login import LoginError, login as garmin_login
from claude_coach.config import settings
from claude_coach.db.models import (
    DailyMetric,
    GarminActivity,
    Insight,
    Session as SessionRow,
)
from claude_coach.db.session import get_db
from claude_coach.services.plan_repo import list_plan_slugs
from claude_coach.services.profile import load_profile

router = APIRouter(prefix="/admin", tags=["admin"])

Db = Annotated[DbSession, Depends(get_db)]


# ─── System status ────────────────────────────────────────────────────────────


class SystemStatus(BaseModel):
    data_dir: str
    profile_configured: bool
    plans_count: int
    active_plan_slug: str | None
    garmin_connected: bool
    garmin_credentials_present: bool
    garmin_tokens_dir: str
    llm_provider_keys: dict[str, bool]
    resend_configured: bool
    db_sessions: int
    db_daily_metrics: int
    db_garmin_activities: int
    db_insights: int


@router.get("/system", response_model=SystemStatus)
def system(db: Db) -> SystemStatus:
    tokens_dir = settings.garmin_tokens_dir
    garmin_connected = (tokens_dir / "oauth2_token.json").exists()
    plans = list_plan_slugs()
    return SystemStatus(
        data_dir=str(settings.data_dir),
        profile_configured=load_profile() is not None,
        plans_count=len(plans),
        active_plan_slug=plans[0] if plans else None,
        garmin_connected=garmin_connected,
        garmin_credentials_present=bool(
            settings.garmin_email and settings.garmin_password
        ),
        garmin_tokens_dir=str(tokens_dir),
        llm_provider_keys={
            "anthropic": bool(settings.anthropic_api_key),
            "openai": bool(settings.openai_api_key),
        },
        resend_configured=bool(
            settings.resend_api_key
            and settings.resend_from_email
            and settings.weekly_report_to_email
        ),
        db_sessions=db.execute(select(func.count(SessionRow.id))).scalar_one(),
        db_daily_metrics=db.execute(select(func.count(DailyMetric.date))).scalar_one(),
        db_garmin_activities=db.execute(
            select(func.count(GarminActivity.activity_id))
        ).scalar_one(),
        db_insights=db.execute(select(func.count(Insight.id))).scalar_one(),
    )


# ─── Garmin connect ───────────────────────────────────────────────────────────


class GarminConnectRequest(BaseModel):
    # Optional override of env credentials. Empty values fall back to env.
    email: str | None = None
    password: str | None = None
    # If MFA is enabled on the account, the user provides the code on a
    # second call after they receive it. (Each attempt triggers a fresh
    # MFA challenge, so the code must come within ~10 minutes of the call
    # that triggered it. See note below.)
    mfa_code: str | None = None


class GarminConnectResponse(BaseModel):
    connected: bool
    needs_mfa: bool = False
    detail: str | None = None
    tokens_path: str | None = None
    last_attempt_at: datetime


@router.post("/garmin/connect", response_model=GarminConnectResponse)
def garmin_connect(payload: GarminConnectRequest | None = None) -> GarminConnectResponse:
    payload = payload or GarminConnectRequest()
    email = payload.email or settings.garmin_email
    password = payload.password or settings.garmin_password
    if not email or not password:
        raise HTTPException(
            422,
            "garmin credentials missing — set GARMIN_EMAIL and GARMIN_PASSWORD env "
            "vars or pass them in the body",
        )

    prompt_mfa = (lambda: payload.mfa_code) if payload.mfa_code else None
    try:
        garmin_login(email, password, prompt_mfa=prompt_mfa)
    except LoginError as exc:
        msg = str(exc)
        if "MFA" in msg.upper():
            return GarminConnectResponse(
                connected=False,
                needs_mfa=True,
                detail=(
                    "Garmin pediu MFA. Submeta de novo com `mfa_code` no body. "
                    "Atenção: cada chamada dispara um código novo no seu e-mail."
                ),
                last_attempt_at=datetime.now(UTC),
            )
        raise HTTPException(502, f"garmin login failed: {msg}") from exc

    return GarminConnectResponse(
        connected=True,
        tokens_path=str(settings.garmin_tokens_dir),
        last_attempt_at=datetime.now(UTC),
    )


class GarminStatusResponse(BaseModel):
    connected: bool
    tokens_dir: str
    has_oauth2_token: bool
    has_oauth1_token: bool


@router.get("/garmin/status", response_model=GarminStatusResponse)
def garmin_status() -> GarminStatusResponse:
    d = settings.garmin_tokens_dir
    return GarminStatusResponse(
        connected=(d / "oauth2_token.json").exists(),
        tokens_dir=str(d),
        has_oauth2_token=(d / "oauth2_token.json").exists(),
        has_oauth1_token=(d / "oauth1_token.json").exists(),
    )


@router.delete("/garmin/tokens", status_code=204)
def garmin_disconnect() -> None:
    """Delete persisted Garmin tokens (forces re-login next request)."""
    d = settings.garmin_tokens_dir
    for name in ("oauth1_token.json", "oauth2_token.json"):
        p = d / name
        if p.exists():
            p.unlink()


# ─── Garmin sync helpers (manual backfill from the UI) ───────────────────────


class GarminBackfillRequest(BaseModel):
    start: str  # ISO date
    end: str  # ISO date


class GarminBackfillResponse(BaseModel):
    days: int
    ok: int
    errors: list[dict[str, Any]]


@router.post("/garmin/backfill", response_model=GarminBackfillResponse)
def garmin_backfill(payload: GarminBackfillRequest, db: Db) -> GarminBackfillResponse:
    from datetime import date as date_cls, timedelta

    from claude_coach.services.garmin_sync import service as sync_service

    try:
        start = date_cls.fromisoformat(payload.start)
        end = date_cls.fromisoformat(payload.end)
    except ValueError as exc:
        raise HTTPException(422, f"bad date: {exc}") from exc
    if end < start:
        raise HTTPException(422, "end must be >= start")
    if (end - start).days > 400:
        raise HTTPException(422, "max 400 days per backfill")

    ok = 0
    errors: list[dict[str, Any]] = []
    d = start
    while d <= end:
        result = sync_service.sync_day(db, day=d)
        if result.status == "ok":
            ok += 1
        else:
            errors.append({"date": str(d), "error": result.error})
        d += timedelta(days=1)
    return GarminBackfillResponse(
        days=(end - start).days + 1,
        ok=ok,
        errors=errors,
    )
