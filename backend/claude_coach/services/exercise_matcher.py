"""String-to-canonical-exercise matcher.

Two-stage pipeline:
1. Deterministic Unicode-folded matching against names + aliases.
2. If stage 1 falls below the LLM-fallback threshold, ask the LLM to choose
   among the catalog entries (or return null if genuinely new).

The deterministic stage handles ~95% of cases for free; the LLM stage catches
rephrasings that exact/substring/token-overlap miss.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass

from claude_coach.domain.exercise import Exercise
from claude_coach.services.exercise_catalog import ExerciseCatalog

log = logging.getLogger(__name__)

# Below this confidence, we consult the LLM before declaring the match.
# 0.9 matches the parser's AUTO threshold — anything that would land in the
# "review needed" tier gets a free LLM second-opinion before being flagged.
LLM_FALLBACK_THRESHOLD = 0.9


@dataclass(frozen=True)
class MatchResult:
    exercise_id: str | None
    confidence: float  # 0.0 .. 1.0
    reason: str  # short explanation for REVIEW.md


def _fold(s: str) -> str:
    """Lowercase + strip accents + collapse whitespace/punctuation to single spaces."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    out = []
    prev_space = True
    for c in s:
        if c.isalnum():
            out.append(c)
            prev_space = False
        else:
            if not prev_space:
                out.append(" ")
            prev_space = True
    return "".join(out).strip()


def _all_keys(ex: Exercise) -> list[str]:
    return [_fold(ex.name)] + [_fold(a) for a in ex.aliases]


def _token_overlap(a: str, b: str) -> float:
    """Jaccard on whitespace tokens — cheap, fine for short exercise names."""
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def deterministic_match(raw_name: str, catalog: ExerciseCatalog) -> MatchResult:
    """Stage 1: pure-Python folded matching. No external calls."""
    folded_query = _fold(raw_name)
    best: tuple[Exercise, float, str] | None = None

    for ex in catalog.all():
        for key in _all_keys(ex):
            if key == folded_query:
                return MatchResult(ex.id, 1.0, f"exact match on '{key}'")
            if folded_query in key or key in folded_query:
                score = 0.85
                if best is None or score > best[1]:
                    best = (ex, score, f"substring match on '{key}'")
            jacc = _token_overlap(folded_query, key)
            if jacc >= 0.5:
                score = 0.6 + 0.3 * jacc  # 0.6..0.9
                if best is None or score > best[1]:
                    best = (ex, score, f"token overlap {jacc:.2f} with '{key}'")

    if best is None:
        return MatchResult(None, 0.0, "no candidates")

    ex, score, reason = best
    return MatchResult(ex.id, score, reason)


def llm_fallback_match(raw_name: str, catalog: ExerciseCatalog) -> MatchResult:
    """Stage 2: ask the LLM to pick from the catalog. Returns None for genuinely new exercises."""
    # Lazy import to keep deterministic_match free of LLM dependencies.
    from claude_coach.adapters.llm.base import Message, TextPart
    from claude_coach.adapters.llm.router import router

    entries = [
        {
            "id": ex.id,
            "name": ex.name,
            "aliases": ex.aliases,
            "muscle_group": ex.primary_muscle_group,
            "equipment": ex.equipment,
        }
        for ex in catalog.all()
    ]
    catalog_json = json.dumps(entries, ensure_ascii=False)

    user_prompt = (
        "Match this Brazilian Portuguese exercise name to one entry in the catalog.\n"
        f"Exercise: {raw_name!r}\n\n"
        f"Catalog: {catalog_json}\n\n"
        "Return ONLY a JSON object with this exact shape:\n"
        '{"exercise_id": "<id-or-null>", "confidence": <float 0..1>, "reason": "<short>"}\n'
        "Use null when the exercise is genuinely not in the catalog (a different "
        "movement, not a translation of an existing one)."
    )

    try:
        result = router.complete(
            task_id="exercise_match",
            messages=[Message(role="user", parts=[TextPart(text=user_prompt)])],
            system="You are a careful exercise-name matcher. Respond with JSON only.",
        )
        data = json.loads(result.text)
        ex_id = data.get("exercise_id")
        confidence = float(data.get("confidence", 0.0))
        reason = data.get("reason") or "(no reason given)"

        if ex_id is not None and catalog.by_id(ex_id) is None:
            # LLM hallucinated an id; treat as miss.
            return MatchResult(None, 0.0, f"LLM proposed unknown id {ex_id!r}")

        return MatchResult(ex_id, confidence, f"LLM: {reason}")
    except Exception as exc:
        log.warning("LLM fallback for %r failed: %s", raw_name, exc)
        return MatchResult(None, 0.0, f"LLM fallback failed: {exc}")


def match(
    raw_name: str,
    catalog: ExerciseCatalog,
    use_llm_fallback: bool = True,
) -> MatchResult:
    """Two-stage match. Deterministic first; LLM fallback when confidence is low."""
    initial = deterministic_match(raw_name, catalog)
    if not use_llm_fallback or initial.confidence >= LLM_FALLBACK_THRESHOLD:
        return initial

    fallback = llm_fallback_match(raw_name, catalog)
    # Trust the LLM if it produced a confident match; otherwise keep the
    # deterministic best guess so we don't lose substring hits.
    if fallback.exercise_id and fallback.confidence > initial.confidence:
        return fallback
    return initial
