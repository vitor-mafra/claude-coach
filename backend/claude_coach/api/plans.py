from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from claude_coach.adapters.pdf_parser import parse_pdf
from claude_coach.config import settings
from claude_coach.domain.plan import Plan
from claude_coach.services.plan_repo import (
    PLANS_DIR,
    list_plan_slugs,
    load_plan,
    review_path,
    save_plan,
)
from claude_coach.services.profile import load_profile
from claude_coach.services.schedule_inference import infer_schedule

router = APIRouter(prefix="/plans", tags=["plans"])


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return base or "plan"


@router.get("", response_model=list[str])
def list_plans() -> list[str]:
    return list_plan_slugs()


@router.get("/{slug}", response_model=Plan)
def get_plan(slug: str) -> Plan:
    plan = load_plan(slug)
    if not plan:
        raise HTTPException(404, f"plan {slug!r} not found")
    return plan


@router.get("/{slug}/review")
def get_review(slug: str) -> dict:
    p = review_path(slug)
    if not p.exists():
        raise HTTPException(404, f"REVIEW.md not found for {slug!r}")
    return {"content": p.read_text(encoding="utf-8")}


class PlanUploadResponse(BaseModel):
    slug: str
    plan_yaml_path: str
    review_md_path: str
    scheduled: bool


@router.post("/upload", response_model=PlanUploadResponse, status_code=201)
async def upload_plan(
    pdf: UploadFile = File(...),
    slug: str | None = Form(default=None),
    skip_schedule: bool = Form(default=False),
) -> PlanUploadResponse:
    """Upload a training PDF, parse it, and persist the resulting plan."""
    if not pdf.filename:
        raise HTTPException(422, "missing filename")
    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(422, "expected a .pdf file")

    final_slug = _slugify(slug or Path(pdf.filename).stem)
    plan_dir = PLANS_DIR / final_slug
    plan_dir.mkdir(parents=True, exist_ok=True)
    raw_pdf_dir = PLANS_DIR / "raw"
    raw_pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = raw_pdf_dir / f"{final_slug}.pdf"

    contents = await pdf.read()
    if not contents:
        raise HTTPException(422, "empty upload")
    pdf_path.write_bytes(contents)

    try:
        output = parse_pdf(pdf_path=pdf_path, plan_dir=plan_dir)
    except Exception as exc:
        raise HTTPException(502, f"parse failed: {exc}") from exc

    output.plan.source_pdf = str(pdf_path.relative_to(settings.data_dir.parent))

    scheduled = False
    if not skip_schedule:
        profile = load_profile()
        if profile is not None:
            try:
                inferred = infer_schedule(output.plan, profile)
                output.plan.schedule = inferred.schedule
                output.plan.schedule_rationale = inferred.rationale
                scheduled = True
            except Exception as exc:  # don't block save on schedule failure
                output.plan.schedule_rationale = f"(schedule inference failed: {exc})"

    plan_yaml = save_plan(final_slug, output.plan)
    review_md = review_path(final_slug)
    review_md.write_text(output.review_md, encoding="utf-8")

    return PlanUploadResponse(
        slug=final_slug,
        plan_yaml_path=str(plan_yaml),
        review_md_path=str(review_md),
        scheduled=scheduled,
    )


@router.post("/{slug}/schedule/regenerate", response_model=Plan)
def regenerate_schedule(slug: str) -> Plan:
    """Re-run the scheduling agent against the user's current profile."""
    plan = load_plan(slug)
    if not plan:
        raise HTTPException(404, f"plan {slug!r} not found")
    profile = load_profile()
    inferred = infer_schedule(plan, profile)
    plan.schedule = inferred.schedule
    plan.schedule_rationale = inferred.rationale
    save_plan(slug, plan)
    return plan
