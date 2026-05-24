"""PDF → structured Plan via Claude vision.

Pipeline:
1. Render PDF pages to PNG (cached under data/plans/<slug>/raw/).
2. Send pages + JSON schema instruction to Claude.
3. Validate JSON against Pydantic Plan.
4. Run exercise matcher against the canonical catalog.
5. Persist plan.yaml + REVIEW.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from claude_coach.adapters.llm.base import ImagePart, Message, TextPart
from claude_coach.adapters.llm.router import LLMRouter
from claude_coach.adapters.llm.router import router as default_router
from claude_coach.domain.plan import Plan
from claude_coach.services.exercise_catalog import ExerciseCatalog
from claude_coach.services.exercise_catalog import catalog as default_catalog
from claude_coach.services.exercise_matcher import match as match_exercise

MATCH_AUTO_THRESHOLD = 0.9  # >=  : auto-accept
MATCH_REVIEW_THRESHOLD = 0.6  # >=  : suggest in REVIEW.md
# below 0.6: no suggestion, flag as new exercise


SYSTEM_PROMPT = """You extract structured training plans from Brazilian Portuguese fitness PDFs.
The PDFs combine running schedules (corrida) using HR zones Z1-Z5 with strength
workouts (Treino A, B, C, D) composed of typed blocks.

You MUST return only a single JSON object matching the provided schema, with no prose
before or after, no markdown code fences. If a field is unknown, omit it.
"""

USER_INSTRUCTIONS = """Extract the training plan from these PDF pages.

Key conventions specific to this kind of plan:
- Strength workouts are labelled "TREINO A", "TREINO B", etc. Each contains numbered
  blocks (BLOCO 01, BLOCO 02, ...) whose header tells you the block KIND:
    "AQUECIMENTO" / mobility / pre-workout pieces → DO NOT make these blocks.
      Instead, collect them into the template's `warmups` array as WarmupSuggestion
      objects ({description, duration_min?, video_url?}). Light bodyweight sets shown
      as part of the warmup ("4x15 agachamento c/ peso do corpo") also go in `warmups`.
    "META DE REPETIÇÃO" / "META DE REPETIÇÕES" → kind=meta_reps
    "PIRÂMIDE" → kind=pyramid (reps_per_set from the sequence in parentheses, e.g. 15-12-10-8)
    "BI-SET" → kind=biset (multiple exercises alternated; the "x" prefix is the round count)
    "DROPSET" → kind=dropset
    "ABDOMINAL" / "TABATA" → kind=tabata
- Rest spec ("Intervalo: 45 Seg" / "1 Min" / "1-3 Min") goes into the block's rest object.
- For strength blocks, every exercise becomes an exercise reference with raw_name set to
  the EXACT exercise string as it appears in the PDF (preserve accents).
- Running workouts use weekday badges (3ª FEIRA, 4ª FEIRA, 6ª FEIRA, DOM). These badges
  are hints, NOT scheduling — IGNORE them when filling Plan.schedule. Leave schedule
  EMPTY ({}). Scheduling is done by a separate downstream agent.
- Run segments are sequential rows: each row has a multiplier (1x, 6x), a HR zone label
  (Z1..Z5), and either a distance (km/metros) or duration (min). Convert 500 metros to
  0.5 km. Each row is a RunSegment.
- Running workout TEMPLATES still need template_ids. Use stable descriptive ids based on
  the workout's character: "run-intervalado-500m", "run-continuo-6km",
  "run-fartlek-1-3", "run-longo", etc. Avoid weekday-based ids since the scheduler
  decides days.
- Run workout kinds:
    "INTERVALADO" → interval_run
    "CONTÍNUO" → continuous_run
    "FARTLEK" → fartlek
- Use template_id "A", "B", "C", "D" for strength workouts in the order they appear.
- weeks_duration is 1 unless explicitly stated.

Schema:
"""

JSON_REMINDER = "\nReturn ONLY the JSON object."


def render_pdf_to_images(pdf_path: Path, output_dir: Path, dpi: int = 144) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for i in range(len(pdf)):
            out_path = output_dir / f"page_{i + 1:02d}.png"
            if not out_path.exists():
                page = pdf[i]
                bitmap = page.render(scale=dpi / 72)
                bitmap.to_pil().save(out_path)
                page.close()
            paths.append(out_path)
    finally:
        pdf.close()
    return paths


def _strip_code_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        # drop the leading ```lang line
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines)
    return t


@dataclass
class ParseOutput:
    plan: Plan
    review_md: str
    raw_response_text: str
    raw_response_path: Path | None


def _build_review_md(plan: Plan, catalog: ExerciseCatalog) -> tuple[str, Plan]:
    """Run exercise matching + emit a REVIEW.md summary.

    Returns (review_md, plan-with-matched-exercise-refs).
    """
    seen_raw: dict[str, tuple[str | None, float, str]] = {}

    def _matched(raw: str) -> tuple[str | None, float, str]:
        if raw in seen_raw:
            return seen_raw[raw]
        result = match_exercise(raw, catalog)
        seen_raw[raw] = (result.exercise_id, result.confidence, result.reason)
        return seen_raw[raw]

    # Walk every block and tag exercise refs
    for tpl in plan.templates.values():
        for block in tpl.blocks:
            refs = []
            if hasattr(block, "exercise"):
                refs.append(block.exercise)
            if hasattr(block, "exercises"):
                refs.extend(bse.exercise for bse in block.exercises)  # type: ignore[attr-defined]
            for ref in refs:
                ex_id, conf, _ = _matched(ref.raw_name)
                if conf >= MATCH_AUTO_THRESHOLD:
                    ref.exercise_id = ex_id
                    ref.confidence = conf
                elif conf >= MATCH_REVIEW_THRESHOLD:
                    ref.exercise_id = ex_id
                    ref.confidence = conf
                else:
                    ref.exercise_id = None
                    ref.confidence = conf

    # Build review summary
    auto_ok: list[str] = []
    review_needed: list[str] = []
    no_match: list[str] = []
    for raw, (ex_id, conf, reason) in sorted(seen_raw.items()):
        line = f"- `{raw}` → **{ex_id or '∅'}** (conf={conf:.2f}, {reason})"
        if conf >= MATCH_AUTO_THRESHOLD:
            auto_ok.append(line)
        elif conf >= MATCH_REVIEW_THRESHOLD:
            review_needed.append(line)
        else:
            no_match.append(f"- `{raw}` — no catalog match (conf={conf:.2f}). "
                            "Add to data/exercises/ or correct raw_name.")

    md = ["# Plan import review\n"]
    md.append(f"**Plan:** {plan.name}\n")
    md.append(f"**Templates:** {', '.join(plan.templates.keys())}\n")
    md.append(f"**Schedule:** {', '.join(f'{a.weekday}={a.template_id}' for a in plan.schedule)}\n")

    md.append("\n## Exercises needing your attention\n")
    if no_match:
        md.append("### ❌ No catalog match\n")
        md.extend(no_match)
        md.append("")
    if review_needed:
        md.append("### ⚠️ Low confidence — please verify\n")
        md.extend(review_needed)
        md.append("")
    if not no_match and not review_needed:
        md.append("_None — all exercises matched the catalog with high confidence._\n")

    md.append("\n## ✅ Auto-matched\n")
    if auto_ok:
        md.extend(auto_ok)
    else:
        md.append("_(none)_")
    md.append("\n")

    return "\n".join(md), plan


def parse_pdf(
    pdf_path: Path,
    plan_dir: Path,
    router: LLMRouter | None = None,
    catalog: ExerciseCatalog | None = None,
) -> ParseOutput:
    router = router or default_router
    catalog = catalog or default_catalog

    raw_dir = plan_dir / "raw"
    image_paths = render_pdf_to_images(pdf_path, raw_dir)

    schema_json = json.dumps(Plan.model_json_schema(), indent=2, ensure_ascii=False)

    parts: list = [
        TextPart(text=USER_INSTRUCTIONS + schema_json + JSON_REMINDER),
    ]
    parts.extend(ImagePart(path=p) for p in image_paths)

    message = Message(role="user", parts=parts)

    result = router.complete(
        task_id="pdf_parse",
        messages=[message],
        system=SYSTEM_PROMPT,
    )

    raw_text = result.text
    json_text = _strip_code_fences(raw_text)

    # Persist raw response for debugging even if validation fails.
    raw_response_path = plan_dir / "raw_response.json"
    raw_response_path.write_text(raw_text, encoding="utf-8")

    data = json.loads(json_text)
    plan = Plan.model_validate(data)

    review_md, plan = _build_review_md(plan, catalog)

    return ParseOutput(
        plan=plan,
        review_md=review_md,
        raw_response_text=raw_text,
        raw_response_path=raw_response_path,
    )
