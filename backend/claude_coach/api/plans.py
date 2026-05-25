from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from claude_coach.adapters.pdf_parser import parse_pdf
from claude_coach.api.security import rate_limit_expensive
from claude_coach.config import settings
from claude_coach.domain.plan import Plan
from claude_coach.services.plan_repo import (
    PLANS_DIR,
    is_safe_slug,
    list_plan_slugs,
    load_plan,
    review_path,
    save_plan,
    slugify,
)
from claude_coach.services.profile import load_profile
from claude_coach.services.schedule_inference import infer_schedule

router = APIRouter(prefix="/plans", tags=["plans"])


def _require_safe_slug(slug: str) -> str:
    if not is_safe_slug(slug):
        raise HTTPException(400, "invalid slug")
    return slug


@router.get("", response_model=list[str])
def list_plans() -> list[str]:
    return list_plan_slugs()


@router.get("/{slug}", response_model=Plan)
def get_plan(slug: str) -> Plan:
    _require_safe_slug(slug)
    plan = load_plan(slug)
    if not plan:
        raise HTTPException(404, f"plan {slug!r} not found")
    return plan


@router.get("/{slug}/review")
def get_review(slug: str) -> dict:
    _require_safe_slug(slug)
    p = review_path(slug)
    if not p.exists():
        raise HTTPException(404, f"REVIEW.md not found for {slug!r}")
    return {"content": p.read_text(encoding="utf-8")}


class PlanUploadResponse(BaseModel):
    slug: str
    plan_yaml_path: str
    review_md_path: str
    scheduled: bool


@router.post(
    "/upload",
    response_model=PlanUploadResponse,
    status_code=201,
    dependencies=[Depends(rate_limit_expensive("plan_upload"))],
)
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
    if pdf.content_type and pdf.content_type not in (
        "application/pdf",
        "application/octet-stream",
    ):
        raise HTTPException(422, "content-type must be application/pdf")

    # Bounded read avoids OOM on a hostile/oversized upload.
    contents = await pdf.read(settings.max_upload_bytes + 1)
    if not contents:
        raise HTTPException(422, "empty upload")
    if len(contents) > settings.max_upload_bytes:
        raise HTTPException(
            413,
            f"file too large (max {settings.max_upload_bytes // (1024 * 1024)} MB)",
        )
    if not contents.startswith(b"%PDF"):
        raise HTTPException(422, "not a valid PDF (missing magic bytes)")

    final_slug = slugify(slug or Path(pdf.filename).stem)
    if not is_safe_slug(final_slug):
        raise HTTPException(422, "could not derive a safe slug")
    plan_dir = PLANS_DIR / final_slug
    plan_dir.mkdir(parents=True, exist_ok=True)
    raw_pdf_dir = PLANS_DIR / "raw"
    raw_pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = raw_pdf_dir / f"{final_slug}.pdf"
    pdf_path.write_bytes(contents)

    try:
        output = parse_pdf(pdf_path=pdf_path, plan_dir=plan_dir)
    except Exception as exc:
        # Don't echo internal library error messages to clients.
        raise HTTPException(502, "PDF parse failed; check server logs") from exc

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


@router.post(
    "/{slug}/schedule/regenerate",
    response_model=Plan,
    dependencies=[Depends(rate_limit_expensive("schedule_regenerate"))],
)
def regenerate_schedule(slug: str) -> Plan:
    """Re-run the scheduling agent against the user's current profile."""
    _require_safe_slug(slug)
    plan = load_plan(slug)
    if not plan:
        raise HTTPException(404, f"plan {slug!r} not found")
    profile = load_profile()
    inferred = infer_schedule(plan, profile)
    plan.schedule = inferred.schedule
    plan.schedule_rationale = inferred.rationale
    save_plan(slug, plan)
    return plan
