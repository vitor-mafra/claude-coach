"""LLM-driven schedule inference for hybrid athletes.

Given a parsed Plan (templates + metadata) and the user's Profile, propose a
weekly schedule honoring:
- Profile.training_days (skip days the user marks as rest)
- Hybrid double-sessions on the same day are OK and expected when needed
- Avoid heavy-legs strength + hard run on the same day
- Spread strength muscle groups
- Hard runs (intervalado, fartlek) prefer non-leg-strength days
- Sunday long run is a common convention

This service IS the coach's first decision-making moment. Keep the prompt rich
and explicit so the model has the constraints to reason from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from claude_coach.adapters.llm.base import Message, TextPart
from claude_coach.adapters.llm.router import LLMRouter
from claude_coach.adapters.llm.router import router as default_router
from claude_coach.domain.plan import Plan, Schedule, WorkoutTemplate
from claude_coach.domain.profile import Profile, Weekday

ORDERED_WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class InferredSchedule:
    schedule: Schedule
    rationale: str


def _template_summary(template: WorkoutTemplate) -> dict:
    summary: dict = {
        "template_id": template.template_id,
        "kind": template.kind,
        "name": template.name,
    }
    if template.kind == "strength":
        # Surface the muscle focus + block mix to help the LLM avoid back-to-backs.
        block_kinds = sorted({b.kind for b in template.blocks})
        summary["block_kinds"] = block_kinds
        muscle_hints = _extract_muscle_hints(template)
        if muscle_hints:
            summary["muscle_focus"] = muscle_hints
    elif template.kind == "run":
        run_kind: Literal["interval_run", "continuous_run", "fartlek"] | None = None
        zones: set[str] = set()
        total_km = 0.0
        for block in template.blocks:
            if block.kind in ("interval_run", "continuous_run", "fartlek"):
                run_kind = block.kind  # type: ignore[assignment]
                for seg in block.segments:  # type: ignore[attr-defined]
                    zones.add(seg.hr_zone)
                    if seg.distance_km is not None:
                        total_km += seg.distance_km * seg.repeats
        summary["run_kind"] = run_kind
        summary["zones"] = sorted(zones)
        if total_km > 0:
            summary["approx_total_km"] = round(total_km, 1)
    return summary


def _extract_muscle_hints(template: WorkoutTemplate) -> list[str]:
    """Heuristically pull muscle keywords from template name (e.g., 'Inferiores + abs')."""
    name = template.name.lower()
    hints: list[str] = []
    mapping = {
        "inferiores": "lower",
        "inferior": "lower",
        "membros inferiores": "lower",
        "peito": "push",
        "ombro": "push",
        "ombros": "push",
        "biceps": "pull",
        "bíceps": "pull",
        "costas": "pull",
        "triceps": "push",
        "tríceps": "push",
        "abs": "core",
    }
    for keyword, tag in mapping.items():
        if keyword in name and tag not in hints:
            hints.append(tag)
    return hints


SYSTEM_PROMPT = """You are a coach scheduling a hybrid athlete's training week.
A "hybrid athlete" trains both strength and running in the same week, sometimes
on the same day (two sessions). Return only a single JSON object — no prose,
no markdown — matching the schema described in the user message.
"""


USER_PROMPT_HEADER = """Build a weekly schedule for this athlete.

HARD CONSTRAINTS (violating these is a failure):
- Output MUST include every weekday key: mon, tue, wed, thu, fri, sat, sun.
- Use ONLY template_ids that appear in `templates`. Spelling must match exactly.
- Each template MUST appear EXACTLY ONCE in the week. No duplicates. No omissions.
  (If templates.length > training_days.length, some days will have TWO sessions.
   If templates.length < training_days.length, some training_days will be empty.)
- Sessions on a day are an ORDERED list. When stacking run + strength, put the
  CARDIO FIRST (assumed AM) and STRENGTH SECOND (assumed PM).
- A day NOT in `training_days` MUST be an empty list `[]`.

SOFT PREFERENCES (apply within hard constraints, in priority order):
1. AVOID stacking a hard run (interval_run, fartlek) with a heavy lower-body
   strength session ("inferiores", "lower") on the same day.
2. AVOID two strength sessions on the same day. Prefer run+strength stacking.
3. WHEN stacking is necessary, prefer (easy run = continuous_run) + (strength).
4. PREFER hard runs (interval_run, fartlek) on days WITHOUT lower-body strength
   (so they stack with push/pull, not legs).
5. PREFER the long/Sunday continuous run on Sunday if Sunday is a training day.
6. PREFER alternating strength muscle focus (lower → push → pull → push) across days.
7. PREFER at least one full rest day per week if training_days has 7 entries.

Return JSON with this exact shape (no markdown, no prose outside the JSON):
{
  "schedule": {
    "mon": ["template-id-1"], "tue": ["a","b"], "wed": [], ...
    "sun": []
  },
  "rationale": "<2-4 sentences explaining the structure and tradeoffs>"
}
"""


def build_schedule_payload(plan: Plan, profile: Profile | None) -> dict:
    return {
        "training_days": (
            profile.training_days if profile else list(ORDERED_WEEKDAYS)
        ),
        "templates": [_template_summary(t) for t in plan.templates.values()],
        "plan_goal": plan.goal,
        "plan_level": plan.level,
    }


def infer_schedule(
    plan: Plan,
    profile: Profile | None,
    router: LLMRouter | None = None,
) -> InferredSchedule:
    router = router or default_router

    payload = build_schedule_payload(plan, profile)

    user_text = (
        USER_PROMPT_HEADER
        + "\nInput:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )

    result = router.complete(
        task_id="schedule_inference",
        messages=[Message(role="user", parts=[TextPart(text=user_text)])],
        system=SYSTEM_PROMPT,
    )

    parsed = json.loads(result.text)
    raw_schedule = parsed.get("schedule") or parsed  # tolerate flat response

    schedule: Schedule = {}
    valid_ids = set(plan.templates.keys())
    for wd in ORDERED_WEEKDAYS:
        entries = raw_schedule.get(wd) or []
        if not isinstance(entries, list):
            entries = []
        # filter out invalid template ids defensively
        schedule[wd] = [tid for tid in entries if tid in valid_ids]

    rationale = parsed.get("rationale", "").strip() or "(no rationale provided)"

    return InferredSchedule(schedule=schedule, rationale=rationale)
