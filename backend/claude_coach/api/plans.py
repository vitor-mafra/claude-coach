from fastapi import APIRouter, HTTPException

from claude_coach.domain.plan import Plan
from claude_coach.services.plan_repo import list_plan_slugs, load_plan, review_path, save_plan
from claude_coach.services.profile import load_profile
from claude_coach.services.schedule_inference import infer_schedule

router = APIRouter(prefix="/plans", tags=["plans"])


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
