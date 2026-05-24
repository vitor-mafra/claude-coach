"""CLI entry: parse a training PDF into structured plan.yaml + infer schedule.

Pipeline:
1. PDF → vision LLM → structured Plan (templates only; schedule left empty).
2. Schedule inference LLM → fills Plan.schedule honoring user profile.
3. Persist plan.yaml + REVIEW.md.

Usage:
    uv run python scripts/parse_pdf.py [PDF_PATH] [--slug SLUG] [--skip-schedule]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from claude_coach.adapters.pdf_parser import parse_pdf  # noqa: E402
from claude_coach.config import REPO_ROOT as CFG_REPO_ROOT  # noqa: E402
from claude_coach.services.plan_repo import review_path, save_plan  # noqa: E402
from claude_coach.services.profile import load_profile  # noqa: E402
from claude_coach.services.schedule_inference import (  # noqa: E402
    ORDERED_WEEKDAYS,
    infer_schedule,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a training plan PDF.")
    parser.add_argument(
        "pdf",
        nargs="?",
        default=str(CFG_REPO_ROOT / "data" / "plans" / "raw" / "time-hibrido-nivel-1.pdf"),
        help="Path to PDF (default: data/plans/raw/time-hibrido-nivel-1.pdf)",
    )
    parser.add_argument("--slug", help="Plan slug (default: derived from PDF filename)")
    parser.add_argument(
        "--skip-schedule",
        action="store_true",
        help="Skip the schedule inference step (leave Plan.schedule empty).",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    slug = args.slug or pdf_path.stem
    plan_dir = CFG_REPO_ROOT / "data" / "plans" / slug
    plan_dir.mkdir(parents=True, exist_ok=True)

    print(f"→ Parsing {pdf_path.name} into plans/{slug}/")
    print("  step 1/2: vision LLM extracting templates …")
    output = parse_pdf(pdf_path=pdf_path, plan_dir=plan_dir)
    output.plan.source_pdf = str(pdf_path.relative_to(CFG_REPO_ROOT))

    if not args.skip_schedule:
        print("  step 2/2: scheduling agent placing templates into the week …")
        profile = load_profile()
        inferred = infer_schedule(output.plan, profile)
        output.plan.schedule = inferred.schedule
        output.plan.schedule_rationale = inferred.rationale

    plan_yaml_path = save_plan(slug, output.plan)
    review_md_path = review_path(slug)
    review_md_path.write_text(output.review_md, encoding="utf-8")

    print()
    print(f"✓ Wrote {plan_yaml_path.relative_to(CFG_REPO_ROOT)}")
    print(f"✓ Wrote {review_md_path.relative_to(CFG_REPO_ROOT)}")
    if output.plan.schedule:
        print()
        print("Schedule:")
        for wd in ORDERED_WEEKDAYS:
            entries = output.plan.schedule.get(wd, [])
            label = " + ".join(entries) if entries else "—"
            print(f"  {wd}: {label}")
        if output.plan.schedule_rationale:
            print()
            print("Rationale:", output.plan.schedule_rationale)
    print()
    print("Next: open the REVIEW.md and verify any low-confidence or unmatched exercises.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
