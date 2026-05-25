"""Read/write parsed plans living under data/plans/<slug>/plan.yaml."""

import re
from pathlib import Path

import yaml

from claude_coach.config import settings
from claude_coach.domain.plan import Plan

PLANS_DIR: Path = settings.data_dir / "plans"

_SAFE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def is_safe_slug(slug: str) -> bool:
    """Plan slugs are user-supplied. Constrain to a known-safe character set
    so they can never escape PLANS_DIR via traversal or absolute paths."""
    return bool(_SAFE_SLUG_RE.match(slug))


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return base or "plan"


def _slug_dirs() -> list[Path]:
    if not PLANS_DIR.exists():
        return []
    return [
        d for d in sorted(PLANS_DIR.iterdir()) if d.is_dir() and (d / "plan.yaml").exists()
    ]


def list_plan_slugs() -> list[str]:
    return [d.name for d in _slug_dirs()]


def load_plan(slug: str) -> Plan | None:
    plan_path = PLANS_DIR / slug / "plan.yaml"
    if not plan_path.exists():
        return None
    with plan_path.open() as f:
        data = yaml.safe_load(f)
    return Plan.model_validate(data)


def save_plan(slug: str, plan: Plan) -> Path:
    plan_dir = PLANS_DIR / slug
    plan_dir.mkdir(parents=True, exist_ok=True)
    out = plan_dir / "plan.yaml"
    with out.open("w") as f:
        yaml.safe_dump(plan.model_dump(mode="json"), f, allow_unicode=True, sort_keys=False)
    return out


def review_path(slug: str) -> Path:
    return PLANS_DIR / slug / "REVIEW.md"
