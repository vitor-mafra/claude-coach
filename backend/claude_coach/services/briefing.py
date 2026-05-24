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


class BriefingContext(BaseModel):
    date: date_cls
    workouts: list[PlannedWorkout]
    exercises_history: list[ExerciseHistory]
    garmin: GarminToday | None
    recent_activities: list[dict[str, Any]]  # last 7 days
    session_notes: list[str]  # last 5 free-text notes


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

    return BriefingContext(
        date=day,
        workouts=workouts,
        exercises_history=history,
        garmin=_garmin_today(db, day),
        recent_activities=_recent_activities(db, day),
        session_notes=_recent_session_notes(db, day),
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

    for w in ctx.workouts:
        parts.append(f"\n## Treino planejado: {w.name} ({w.kind})")
        for ex in w.exercises:
            sets_desc = ", ".join(
                f"{s.set_idx}×{s.planned_reps or '?'}" for s in ex.sets
            )
            parts.append(f"- {ex.exercise_name} ({ex.kind}): {sets_desc}")

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
