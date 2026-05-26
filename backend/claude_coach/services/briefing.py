"""Pre-workout briefing.

Pipeline (on-demand, when user taps "vou treinar agora"):

1. Resolve today's workout from the active plan.
2. Best-effort sync today's Garmin (refresh body battery / HRV / stress).
3. Build context: planned exercises + history of recent sessions for each +
   today's daily metrics + last few sessions' free-text notes.
4. Call LLMRouter task_id="briefing" → markdown.
5. Persist as Insight row + return text.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from dataclasses import dataclass
from datetime import UTC, date as date_cls, datetime
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from claude_coach.adapters.llm.base import Message
from claude_coach.adapters.llm.router import LLMRouter
from claude_coach.adapters.llm.router import router as default_router
from claude_coach.db.models import (
    DailyMetric,
    GarminActivity,
    Insight,
    Session as SessionRow,
    SessionSet,
    Tested1RM,
)
from claude_coach.services.exercise_catalog import catalog as exercise_catalog
from claude_coach.services.garmin_sync import service as garmin_sync
from claude_coach.services.sessions import (
    PlannedExercise,
    PlannedWorkout,
    load_active_plan,
    planned_workout,
    workout_for_date,
)

log = structlog.get_logger(__name__)

BRIEFING_SYSTEM = textwrap.dedent(
    """\
    Você é o Claude Coach: agente pessoal de um atleta amador de musculação +
    corrida (hibrido). Sua tarefa é gerar um briefing curto, prático e em
    português pt-BR para o treino que ele vai fazer AGORA.

    Estrutura sugerida (use markdown, ~150-250 palavras no total):

    ### Como você está hoje
    1 parágrafo curto: leitura do estado fisiológico baseado em Body Battery,
    HRV (compare com a média recente se disponível), sono, stress. Tom direto,
    sem floreio. Sinalize alertas claros (sono < 6h, HRV bem abaixo do normal,
    body battery muito baixo).

    ### Foco do treino
    1-2 frases citando o que vai treinar e o que vale priorizar hoje
    considerando como ele está.

    ### Sugestões por exercício
    Lista curta dos exercícios principais. Para cada um:
    - Carga sugerida baseada no histórico recente (use os pesos das últimas
      sessões; respeite o feeling — se nas últimas sessões reps caíram, sugira
      manter ou baixar). Cite o número.
    - 1 dica técnica/mental opcional se houver padrão claro nas notas livres.

    ### Corrida (quando houver)
    Para CADA segmento de corrida planejado, cite a zona (Z1-Z5) E o intervalo
    de bpm correspondente (use as zonas fornecidas no contexto, NÃO calcule por
    %FCmax sozinho). Formato: "6× 500m em Z5 (185-206 bpm) — empurra forte".
    Se houver dado Garmin do dia (HRV baixo, body battery baixo) sugira ajuste
    pragmático (ex: "fica no piso da Z5, 185 bpm").

    Regras:
    - Nunca invente dados. Se uma métrica está ausente, omita ou diga "sem dado".
    - Não prescreva mais do que o que o plano pede (sem adicionar exercícios).
    - Sugestões de carga são pontuais: "tenta 80kg" não "progrida 5%".
    - Não use emojis. Não use linguagem motivacional vazia ("você consegue!").
    """
)


# ─── Context builder ──────────────────────────────────────────────────────────


class ExerciseHistory(BaseModel):
    exercise_id: str
    exercise_name: str
    recent_sessions: list[dict[str, Any]]  # latest first
    best_recent_1rm: float | None = None
    notes: list[str] = []


class GarminToday(BaseModel):
    date: date_cls
    sleep_score: int | None
    sleep_duration_min: int | None
    body_battery_start: int | None
    body_battery_end: int | None
    stress_avg: int | None
    hrv_avg: float | None
    hrv_7d_avg: float | None = None
    sleep_7d_avg: float | None = None


class HRZoneRef(BaseModel):
    zone: str  # Z1..Z5
    low_bpm: int
    high_bpm: int


class BriefingContext(BaseModel):
    date: date_cls
    workouts: list[PlannedWorkout]
    exercises_history: list[ExerciseHistory]
    garmin: GarminToday | None
    recent_activities: list[dict[str, Any]]  # last 7 days
    session_notes: list[str]  # last 5 free-text notes
    hr_zones: list[HRZoneRef] = []
    hr_max: int | None = None
    hr_zones_source: str = "tanaka"  # "garmin" | "tanaka"


@dataclass
class BriefingResult:
    id: int
    content_md: str
    context: BriefingContext


# ----- Garmin context -----


def _garmin_today(db: DbSession, day: date_cls) -> GarminToday | None:
    row = db.get(DailyMetric, day)
    # 7d trailing averages from recent rows
    cutoff_rows = (
        db.execute(
            select(DailyMetric)
            .where(DailyMetric.date < day)
            .order_by(DailyMetric.date.desc())
            .limit(7)
        )
        .scalars()
        .all()
    )

    def _avg(attr: str) -> float | None:
        vals = [getattr(r, attr) for r in cutoff_rows if getattr(r, attr) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    hrv_7d = _avg("hrv_avg")
    sleep_7d = _avg("sleep_score")

    if row is None:
        if hrv_7d is None and sleep_7d is None:
            return None
        return GarminToday(
            date=day,
            sleep_score=None,
            sleep_duration_min=None,
            body_battery_start=None,
            body_battery_end=None,
            stress_avg=None,
            hrv_avg=None,
            hrv_7d_avg=hrv_7d,
            sleep_7d_avg=sleep_7d,
        )

    return GarminToday(
        date=day,
        sleep_score=row.sleep_score,
        sleep_duration_min=row.sleep_duration_min,
        body_battery_start=row.body_battery_start,
        body_battery_end=row.body_battery_end,
        stress_avg=row.stress_avg,
        hrv_avg=row.hrv_avg,
        hrv_7d_avg=hrv_7d,
        sleep_7d_avg=sleep_7d,
    )


def _recent_activities(db: DbSession, day: date_cls) -> list[dict[str, Any]]:
    from datetime import timedelta

    cutoff = day - timedelta(days=7)
    rows = (
        db.execute(
            select(GarminActivity)
            .where(GarminActivity.date >= cutoff, GarminActivity.date <= day)
            .order_by(GarminActivity.date.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "date": str(r.date),
            "sport": r.sport_type,
            "duration_min": round(r.duration_s / 60) if r.duration_s else None,
            "distance_km": r.distance_km,
            "hr_avg": r.hr_avg,
        }
        for r in rows
    ]


# ----- Exercise history -----


def _history_for_exercise(
    db: DbSession,
    exercise_id: str,
    exercise_name: str,
    *,
    limit_sessions: int = 3,
) -> ExerciseHistory:
    """Find latest sessions that included this exercise; report the working sets."""
    set_rows = (
        db.execute(
            select(SessionSet, SessionRow)
            .join(SessionRow, SessionRow.id == SessionSet.session_id)
            .where(SessionSet.exercise_id == exercise_id, SessionSet.is_warmup.is_(False))
            .order_by(SessionRow.date.desc(), SessionSet.set_idx.asc())
        )
        .all()
    )

    sessions: dict[int, dict[str, Any]] = {}
    notes: list[str] = []
    for s, session in set_rows:
        if len(sessions) >= limit_sessions and s.session_id not in sessions:
            break
        bucket = sessions.setdefault(
            s.session_id,
            {"date": str(session.date), "sets": [], "note": session.note},
        )
        bucket["sets"].append(
            {
                "set_idx": s.set_idx,
                "reps": s.actual_reps,
                "weight_kg": s.actual_weight_kg,
                "planned_reps": s.planned_reps,
                "note": s.note,
            }
        )
    notes = [b["note"] for b in sessions.values() if b.get("note")]

    best_1rm_row = (
        db.execute(
            select(Tested1RM)
            .where(Tested1RM.exercise_id == exercise_id)
            .order_by(Tested1RM.date.desc())
            .limit(1)
        )
        .scalar_one_or_none()
    )
    best = best_1rm_row.estimated_1rm if best_1rm_row else None

    return ExerciseHistory(
        exercise_id=exercise_id,
        exercise_name=exercise_name,
        recent_sessions=list(sessions.values()),
        best_recent_1rm=best,
        notes=notes,
    )


def _recent_session_notes(db: DbSession, day: date_cls, limit: int = 5) -> list[str]:
    rows = (
        db.execute(
            select(SessionRow)
            .where(SessionRow.date <= day, SessionRow.note.is_not(None))
            .order_by(SessionRow.date.desc(), SessionRow.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [r.note for r in rows if r.note]


# ----- Top-level builder -----


def _resolve_hr_zones() -> tuple[list[HRZoneRef], int | None, str]:
    """Resolve user's HR zones. Prefer live Garmin config; fall back to Tanaka."""
    from claude_coach.adapters.garmin import adapter as garmin_adapter
    from claude_coach.domain.calculations import (
        hr_zone_bounds,
        hr_zone_bounds_from_floors,
    )
    from claude_coach.services.profile import load_profile

    try:
        z = garmin_adapter.fetch_hr_zones()
    except Exception as exc:
        log.warning("briefing.hr_zones.garmin_fail", error=str(exc))
        z = None

    if z:
        refs = [
            HRZoneRef(
                zone=zone,
                low_bpm=hr_zone_bounds_from_floors(z.zone_floors, z.max_hr, zone)[0],
                high_bpm=hr_zone_bounds_from_floors(z.zone_floors, z.max_hr, zone)[1],
            )
            for zone in ("Z1", "Z2", "Z3", "Z4", "Z5")
            if zone in z.zone_floors
        ]
        return refs, z.max_hr, "garmin"

    profile = load_profile()
    if not profile:
        return [], None, "tanaka"
    fc_max = profile.fc_max_bpm
    refs = [
        HRZoneRef(zone=zone, low_bpm=hr_zone_bounds(fc_max, zone)[0],
                  high_bpm=hr_zone_bounds(fc_max, zone)[1])
        for zone in ("Z1", "Z2", "Z3", "Z4", "Z5")
    ]
    return refs, fc_max, "tanaka"


def build_context(db: DbSession, day: date_cls) -> BriefingContext | None:
    active = load_active_plan()
    if not active:
        return None
    slug, plan = active
    catalog_map = {ex.id: ex.model_dump(mode="json") for ex in exercise_catalog.all()}
    templates = workout_for_date(plan, catalog_map, day)
    workouts = [planned_workout(slug, plan, catalog_map, t, day) for t in templates]

    # Aggregate unique exercises across all workouts of the day.
    seen: dict[str, PlannedExercise] = {}
    for w in workouts:
        for ex in w.exercises:
            seen.setdefault(ex.exercise_id, ex)

    history = [
        _history_for_exercise(db, ex.exercise_id, ex.exercise_name)
        for ex in seen.values()
    ]

    hr_zones, hr_max, hr_source = _resolve_hr_zones()

    return BriefingContext(
        date=day,
        workouts=workouts,
        exercises_history=history,
        garmin=_garmin_today(db, day),
        recent_activities=_recent_activities(db, day),
        session_notes=_recent_session_notes(db, day),
        hr_zones=hr_zones,
        hr_max=hr_max,
        hr_zones_source=hr_source,
    )


def _hash_context(ctx: BriefingContext) -> str:
    blob = ctx.model_dump_json(exclude={"workouts"})
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ─── Prompt + LLM ─────────────────────────────────────────────────────────────


def _render_prompt(ctx: BriefingContext) -> str:
    parts: list[str] = []
    parts.append(f"Data: {ctx.date.isoformat()}")

    if ctx.garmin:
        g = ctx.garmin
        parts.append("\n## Métricas Garmin de hoje")
        parts.append(
            f"- Sono: score {g.sleep_score} ({g.sleep_duration_min} min) "
            f"| média 7d score {g.sleep_7d_avg}"
        )
        parts.append(
            f"- Body Battery: {g.body_battery_start} → {g.body_battery_end} (início → agora)"
        )
        parts.append(f"- Stress médio: {g.stress_avg}")
        parts.append(f"- HRV: {g.hrv_avg} | média 7d {g.hrv_7d_avg}")
    else:
        parts.append("\n## Métricas Garmin de hoje: sem dado")

    if ctx.recent_activities:
        parts.append("\n## Últimos 7 dias de atividades Garmin")
        for a in ctx.recent_activities:
            parts.append(
                f"- {a['date']}: {a['sport']} {a['duration_min']}min "
                f"{a.get('distance_km') or ''} HR {a.get('hr_avg') or '?'}"
            )

    if ctx.hr_zones:
        zone_lines = ", ".join(
            f"{z.zone} {z.low_bpm}-{z.high_bpm}" for z in ctx.hr_zones
        )
        parts.append(
            f"\n## Zonas de FC do atleta (fonte: {ctx.hr_zones_source}, FCmax {ctx.hr_max})"
        )
        parts.append(zone_lines)

    zone_map = {z.zone: (z.low_bpm, z.high_bpm) for z in ctx.hr_zones}

    for w in ctx.workouts:
        parts.append(f"\n## Treino planejado: {w.name} ({w.kind})")
        for ex in w.exercises:
            sets_desc = ", ".join(
                f"{s.set_idx}×{s.planned_reps or '?'}" for s in ex.sets
            )
            parts.append(f"- {ex.exercise_name} ({ex.kind}): {sets_desc}")
        if w.run_segments:
            parts.append("Segmentos da corrida:")
            for seg in w.run_segments:
                dist = f"{seg.distance_km}km" if seg.distance_km else None
                dur = f"{seg.duration_min}min" if seg.duration_min else None
                amount = dist or dur or "?"
                bounds = zone_map.get(seg.hr_zone)
                bpm = f" ({bounds[0]}-{bounds[1]} bpm)" if bounds else ""
                note = f" — {seg.note}" if seg.note else ""
                parts.append(
                    f"- {seg.repeats}× {amount} @ {seg.hr_zone}{bpm}{note}"
                )

    parts.append("\n## Histórico recente por exercício do treino")
    for h in ctx.exercises_history:
        if not h.recent_sessions:
            parts.append(f"- {h.exercise_name}: sem sessões anteriores registradas")
            continue
        parts.append(f"- {h.exercise_name}:")
        for s in h.recent_sessions:
            sets_str = ", ".join(
                f"{x['weight_kg'] or '?'}kg×{x['reps'] or '?'}" for x in s["sets"]
            )
            note = f" | nota: {s['note']}" if s.get("note") else ""
            parts.append(f"    {s['date']}: {sets_str}{note}")
        if h.best_recent_1rm:
            parts.append(f"    1RM estimado mais recente: {round(h.best_recent_1rm, 1)}kg")

    if ctx.session_notes:
        parts.append("\n## Notas livres das últimas sessões")
        for n in ctx.session_notes:
            parts.append(f"- {n}")

    parts.append(
        "\nGere o briefing seguindo a estrutura do system prompt. "
        "Seja conciso. Não invente."
    )
    return "\n".join(parts)


# ─── Service ──────────────────────────────────────────────────────────────────


class BriefingService:
    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self._router = llm_router or default_router

    def generate(
        self,
        db: DbSession,
        day: date_cls | None = None,
        *,
        refresh_garmin: bool = True,
    ) -> BriefingResult | None:
        target = day or datetime.now(UTC).date()
        if refresh_garmin:
            try:
                garmin_sync.sync_day(db, day=target)
            except Exception as exc:
                log.warning("briefing.garmin_refresh.fail", date=str(target), error=str(exc))

        ctx = build_context(db, target)
        if ctx is None:
            return None

        # No workout today (rest day) — still emit a short briefing or skip?
        if not ctx.workouts:
            content = "## Hoje é dia de descanso\n\nSem treino programado pelo cronograma."
            insight = Insight(
                type="briefing",
                target_date=target,
                content_md=content,
                input_context_hash=_hash_context(ctx),
                context_payload=json.loads(ctx.model_dump_json()),
            )
            db.add(insight)
            db.commit()
            db.refresh(insight)
            return BriefingResult(id=insight.id, content_md=content, context=ctx)

        prompt = _render_prompt(ctx)
        result = self._router.complete(
            task_id="briefing",
            messages=[Message.user(prompt)],
            system=BRIEFING_SYSTEM,
        )

        insight = Insight(
            type="briefing",
            target_date=target,
            content_md=result.text,
            llm_provider=result.provider,
            llm_model=result.model,
            input_context_hash=_hash_context(ctx),
            context_payload=json.loads(ctx.model_dump_json()),
        )
        db.add(insight)
        db.commit()
        db.refresh(insight)
        log.info(
            "briefing.generated",
            id=insight.id,
            date=str(target),
            tokens_in=result.input_tokens,
            tokens_out=result.output_tokens,
        )
        return BriefingResult(id=insight.id, content_md=result.text, context=ctx)


service = BriefingService()
