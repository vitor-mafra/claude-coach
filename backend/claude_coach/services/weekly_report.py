"""Weekly report.

Generated every Monday 8h (default, configurable) for the previous ISO week.

Pipeline:
1. Resolve target week (Mon-Sun) — defaults to last completed week.
2. Aggregate:
   - All sessions + sets in the window
   - All Garmin activities
   - Daily metrics (sleep / HRV / body battery / stress trend)
   - Compare against the previous week (deltas)
   - Per-exercise progression: latest set vs same-week-prior
3. Render compact text context for the LLM.
4. Claude Sonnet via task_id="weekly_report" → markdown.
5. Persist:
   - Insight row (type=weekly_report)
   - File data/reports/<YYYY>/W<NN>.md (committed)
6. Caller can then email via resend adapter.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from dataclasses import dataclass
from datetime import UTC, date as date_cls, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from claude_coach.adapters.llm.base import Message
from claude_coach.adapters.llm.router import LLMRouter
from claude_coach.adapters.llm.router import router as default_router
from claude_coach.config import settings
from claude_coach.db.models import (
    DailyMetric,
    GarminActivity,
    Insight,
    Session as SessionRow,
    SessionSet,
    Tested1RM,
)
from claude_coach.services.sessions import WEEKDAY_BY_INDEX, load_active_plan

log = structlog.get_logger(__name__)

REPORTS_DIR = settings.data_dir / "reports"

WEEKLY_REPORT_SYSTEM = textwrap.dedent(
    """\
    Você é o Claude Coach: agente pessoal de um atleta híbrido (musculação +
    corrida). Gere um relatório semanal em português pt-BR, markdown, ~400-700
    palavras. Tom direto, sem motivacional vazio, sem emojis.

    Estrutura:

    ## Resumo da semana
    1 parágrafo: adesão (treinos feitos vs planejados), volume total
    (sessões de força + corrida), qualidade fisiológica geral.

    ## Adesão e volume
    Lista curta com números:
    - Sessões de força: N/M (planejadas)
    - Corridas: N (km totais, duração)
    - Compare com semana anterior se houver dado.

    ## Estado fisiológico
    Tendências de sono, HRV, body battery, stress. Compare com semana
    anterior. Sinalize quedas/melhoras relevantes.

    ## Progressões por exercício
    Lista dos exercícios principais que apareceram nas sessões. Para cada um,
    cargas trabalhadas e se houve progressão, manutenção ou regressão.

    ## Alertas e observações
    Lista curta de coisas que merecem atenção (sono caindo X dias seguidos,
    HRV abaixo da média, estagnação em algum exercício, semanas sem corrida,
    etc.). Se não houver nada relevante, escreva "Sem alertas relevantes."

    ## Recomendação pra semana que vem
    1-2 frases.

    Regras:
    - Nunca invente número. Se um dado está ausente, omita.
    - Não prescreva planos novos — só observe e sugira.
    - Use os números reais do contexto.
    """
)


# ─── Week math ────────────────────────────────────────────────────────────────


def iso_week_window(any_date: date_cls) -> tuple[date_cls, date_cls]:
    """Return (Monday, Sunday) of the ISO week containing `any_date`."""
    monday = any_date - timedelta(days=any_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def last_completed_week(today: date_cls | None = None) -> tuple[date_cls, date_cls]:
    today = today or datetime.now(UTC).date()
    last_sun = today - timedelta(days=today.weekday() + 1)
    return iso_week_window(last_sun)


# ─── Context shape ────────────────────────────────────────────────────────────


class ExerciseProgression(BaseModel):
    exercise_id: str
    sessions: list[dict[str, Any]]  # {date, top_weight, total_volume_kg, reps}
    last_top: float | None = None
    prev_week_top: float | None = None


class WeekSummary(BaseModel):
    sessions_done: int
    sessions_planned: int | None = None
    strength_sessions: int
    run_sessions: int
    run_km_total: float
    run_duration_min_total: int


class GarminTrend(BaseModel):
    days: int
    sleep_avg: float | None = None
    sleep_min: int | None = None
    hrv_avg: float | None = None
    body_battery_avg_start: float | None = None
    body_battery_avg_end: float | None = None
    stress_avg: float | None = None


class OneRMSnapshot(BaseModel):
    exercise_id: str
    week_top_estimated_1rm: float
    last_known_estimated_1rm: float | None = None
    delta_vs_last: float | None = None  # last_known minus prior best (any prior week)


class WeeklyReportContext(BaseModel):
    week_start: date_cls
    week_end: date_cls
    summary: WeekSummary
    prev_summary: WeekSummary | None = None
    garmin: GarminTrend
    prev_garmin: GarminTrend | None = None
    progressions: list[ExerciseProgression]
    one_rm_snapshots: list[OneRMSnapshot] = []
    sessions: list[dict[str, Any]]  # high-level: date, template, note
    notes: list[str]


@dataclass
class WeeklyReportResult:
    id: int
    week_start: date_cls
    week_end: date_cls
    content_md: str
    file_path: Path


# ─── Aggregations ─────────────────────────────────────────────────────────────


def _planned_session_counts(start: date_cls, end: date_cls) -> tuple[int, int, int]:
    """Walk the active plan's schedule day by day and count planned sessions.

    Returns (total, strength, run). If no active plan, returns zeros (caller
    should treat as "unknown" and pass through).
    """
    active = load_active_plan()
    if not active:
        return 0, 0, 0
    _, plan = active
    total = strength = run = 0
    day = start
    while day <= end:
        wd = WEEKDAY_BY_INDEX[day.weekday()]
        for tid in plan.schedule.get(wd, []) or []:
            tpl = plan.templates.get(tid)
            if not tpl:
                continue
            total += 1
            if tpl.kind == "run":
                run += 1
            else:
                strength += 1
        day += timedelta(days=1)
    return total, strength, run


def _classify_session(s: SessionRow) -> str:
    """Use plan template kind when possible; fall back to template_id heuristic."""
    active = load_active_plan()
    if active:
        _, plan = active
        tpl = plan.templates.get(s.workout_template_id)
        if tpl:
            return tpl.kind
    return "run" if "run" in (s.workout_template_id or "").lower() else "strength"


def _summarize_window(
    db: DbSession, start: date_cls, end: date_cls
) -> tuple[WeekSummary, list[dict[str, Any]]]:
    sessions = (
        db.execute(
            select(SessionRow)
            .where(SessionRow.date >= start, SessionRow.date <= end)
            .order_by(SessionRow.date.asc())
        )
        .scalars()
        .all()
    )
    activities = (
        db.execute(
            select(GarminActivity)
            .where(GarminActivity.date >= start, GarminActivity.date <= end)
            .order_by(GarminActivity.date.asc())
        )
        .scalars()
        .all()
    )

    run_acts = [a for a in activities if a.sport_type and "run" in a.sport_type.lower()]
    run_km = sum(a.distance_km or 0 for a in run_acts)
    run_min = sum(round((a.duration_s or 0) / 60) for a in run_acts)

    strength_count = sum(1 for s in sessions if _classify_session(s) == "strength")
    run_session_count = len(run_acts)

    planned_total, _planned_strength, _planned_run = _planned_session_counts(start, end)

    summary = WeekSummary(
        sessions_done=len(sessions),
        sessions_planned=planned_total or None,
        strength_sessions=strength_count,
        run_sessions=run_session_count,
        run_km_total=round(run_km, 2),
        run_duration_min_total=run_min,
    )

    sess_list: list[dict[str, Any]] = []
    for s in sessions:
        sets = (
            db.execute(
                select(SessionSet).where(SessionSet.session_id == s.id)
            )
            .scalars()
            .all()
        )
        sess_list.append(
            {
                "date": str(s.date),
                "template": s.workout_template_id,
                "status": s.status,
                "note": s.note,
                "n_sets": len(sets),
            }
        )
    return summary, sess_list


def _garmin_trend(db: DbSession, start: date_cls, end: date_cls) -> GarminTrend:
    rows = (
        db.execute(
            select(DailyMetric)
            .where(DailyMetric.date >= start, DailyMetric.date <= end)
        )
        .scalars()
        .all()
    )
    if not rows:
        return GarminTrend(days=0)

    def _avg(attr: str) -> float | None:
        vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    sleep_scores = [r.sleep_score for r in rows if r.sleep_score is not None]
    sleep_min_dur = (
        min((r.sleep_duration_min for r in rows if r.sleep_duration_min), default=None)
    )

    return GarminTrend(
        days=len(rows),
        sleep_avg=round(sum(sleep_scores) / len(sleep_scores), 1) if sleep_scores else None,
        sleep_min=sleep_min_dur,
        hrv_avg=_avg("hrv_avg"),
        body_battery_avg_start=_avg("body_battery_start"),
        body_battery_avg_end=_avg("body_battery_end"),
        stress_avg=_avg("stress_avg"),
    )


def _exercise_progressions(
    db: DbSession, start: date_cls, end: date_cls
) -> list[ExerciseProgression]:
    week_rows = (
        db.execute(
            select(SessionSet, SessionRow)
            .join(SessionRow, SessionRow.id == SessionSet.session_id)
            .where(
                SessionRow.date >= start,
                SessionRow.date <= end,
                SessionSet.is_warmup.is_(False),
            )
        )
        .all()
    )

    by_exercise: dict[str, list[tuple[date_cls, float, int]]] = {}
    for s, session in week_rows:
        if s.actual_weight_kg is None or s.actual_reps is None:
            continue
        by_exercise.setdefault(s.exercise_id, []).append(
            (session.date, s.actual_weight_kg, s.actual_reps)
        )

    # Same range, previous week
    prev_start = start - timedelta(days=7)
    prev_end = end - timedelta(days=7)
    prev_rows = (
        db.execute(
            select(SessionSet.exercise_id, func.max(SessionSet.actual_weight_kg))
            .join(SessionRow, SessionRow.id == SessionSet.session_id)
            .where(
                SessionRow.date >= prev_start,
                SessionRow.date <= prev_end,
                SessionSet.is_warmup.is_(False),
            )
            .group_by(SessionSet.exercise_id)
        )
        .all()
    )
    prev_top_by_ex = {ex: w for ex, w in prev_rows}

    out: list[ExerciseProgression] = []
    for exercise_id, entries in by_exercise.items():
        by_date: dict[date_cls, dict[str, Any]] = {}
        for d, w, reps in entries:
            bucket = by_date.setdefault(
                d, {"date": str(d), "top_weight": 0.0, "total_volume_kg": 0.0, "reps": 0}
            )
            if w > bucket["top_weight"]:
                bucket["top_weight"] = w
            bucket["total_volume_kg"] += w * reps
            bucket["reps"] += reps
        sessions_list = sorted(by_date.values(), key=lambda x: x["date"])
        last_top = max((s["top_weight"] for s in sessions_list), default=None)
        out.append(
            ExerciseProgression(
                exercise_id=exercise_id,
                sessions=sessions_list,
                last_top=last_top,
                prev_week_top=prev_top_by_ex.get(exercise_id),
            )
        )
    out.sort(key=lambda p: -(p.last_top or 0))
    return out


def _one_rm_snapshots(
    db: DbSession, week_start: date_cls, week_end: date_cls
) -> list[OneRMSnapshot]:
    """Top derived 1RM per exercise during the week, plus delta vs best prior."""
    week_rows = (
        db.execute(
            select(Tested1RM)
            .where(Tested1RM.date >= week_start, Tested1RM.date <= week_end)
        )
        .scalars()
        .all()
    )
    top_week: dict[str, float] = {}
    for r in week_rows:
        if r.estimated_1rm > top_week.get(r.exercise_id, 0):
            top_week[r.exercise_id] = r.estimated_1rm

    out: list[OneRMSnapshot] = []
    for exercise_id, week_top in top_week.items():
        prior_best = (
            db.execute(
                select(Tested1RM)
                .where(
                    Tested1RM.exercise_id == exercise_id,
                    Tested1RM.date < week_start,
                )
                .order_by(Tested1RM.estimated_1rm.desc())
                .limit(1)
            )
            .scalar_one_or_none()
        )
        prior_val = prior_best.estimated_1rm if prior_best else None
        delta = round(week_top - prior_val, 2) if prior_val is not None else None
        out.append(
            OneRMSnapshot(
                exercise_id=exercise_id,
                week_top_estimated_1rm=round(week_top, 2),
                last_known_estimated_1rm=(
                    round(prior_val, 2) if prior_val is not None else None
                ),
                delta_vs_last=delta,
            )
        )
    out.sort(key=lambda s: -(s.week_top_estimated_1rm))
    return out


def build_context(
    db: DbSession, week_start: date_cls, week_end: date_cls
) -> WeeklyReportContext:
    summary, sessions = _summarize_window(db, week_start, week_end)
    prev_start = week_start - timedelta(days=7)
    prev_end = week_end - timedelta(days=7)
    prev_summary, _ = _summarize_window(db, prev_start, prev_end)

    garmin = _garmin_trend(db, week_start, week_end)
    prev_garmin = _garmin_trend(db, prev_start, prev_end)

    progressions = _exercise_progressions(db, week_start, week_end)
    one_rm = _one_rm_snapshots(db, week_start, week_end)
    notes = [s["note"] for s in sessions if s.get("note")]

    return WeeklyReportContext(
        week_start=week_start,
        week_end=week_end,
        summary=summary,
        prev_summary=prev_summary if prev_summary.sessions_done or prev_garmin.days else None,
        garmin=garmin,
        prev_garmin=prev_garmin if prev_garmin.days else None,
        progressions=progressions,
        one_rm_snapshots=one_rm,
        sessions=sessions,
        notes=notes,
    )


# ─── Prompt ───────────────────────────────────────────────────────────────────


def _fmt_trend(g: GarminTrend) -> str:
    return (
        f"sono médio {g.sleep_avg} (min {g.sleep_min}min), "
        f"HRV {g.hrv_avg}, body battery {g.body_battery_avg_start}→{g.body_battery_avg_end}, "
        f"stress {g.stress_avg}, dias com dado: {g.days}"
    )


def _render_prompt(ctx: WeeklyReportContext) -> str:
    parts: list[str] = []
    parts.append(f"Semana: {ctx.week_start.isoformat()} a {ctx.week_end.isoformat()}\n")

    s = ctx.summary
    parts.append("## Resumo bruto da semana")
    planned_str = (
        f"{s.sessions_done}/{s.sessions_planned}"
        if s.sessions_planned
        else f"{s.sessions_done} (planejadas: sem dado)"
    )
    parts.append(
        f"- Sessões totais: {planned_str} (força {s.strength_sessions}, "
        f"corrida {s.run_sessions})"
    )
    parts.append(
        f"- Corrida: {s.run_km_total}km em {s.run_duration_min_total}min"
    )
    if ctx.prev_summary:
        ps = ctx.prev_summary
        parts.append(
            f"- Semana anterior: {ps.sessions_done} sessões "
            f"(força {ps.strength_sessions}, corrida {ps.run_sessions}, "
            f"{ps.run_km_total}km)"
        )

    parts.append("\n## Garmin desta semana")
    parts.append(f"- {_fmt_trend(ctx.garmin)}")
    if ctx.prev_garmin:
        parts.append(f"- Semana anterior: {_fmt_trend(ctx.prev_garmin)}")

    parts.append("\n## Sessões registradas")
    for sess in ctx.sessions:
        line = f"- {sess['date']} template {sess.get('template')} ({sess.get('n_sets')} sets)"
        if sess.get("note"):
            line += f" — nota: {sess['note']}"
        parts.append(line)
    if not ctx.sessions:
        parts.append("- (nenhuma sessão registrada na semana)")

    parts.append("\n## Progressões por exercício")
    for p in ctx.progressions:
        per_day = ", ".join(
            f"{d['date']}: top {d['top_weight']}kg ({int(d['total_volume_kg'])}kg vol)"
            for d in p.sessions
        )
        delta = ""
        if p.prev_week_top is not None and p.last_top is not None:
            d = p.last_top - p.prev_week_top
            delta = f" (vs sem ant: {'+' if d >= 0 else ''}{round(d, 1)}kg)"
        parts.append(f"- {p.exercise_id}: {per_day}{delta}")
    if not ctx.progressions:
        parts.append("- (sem dados de força nessa semana)")

    if ctx.one_rm_snapshots:
        parts.append("\n## 1RM estimado (Epley) — top desta semana vs melhor anterior")
        for snap in ctx.one_rm_snapshots:
            base = f"- {snap.exercise_id}: {snap.week_top_estimated_1rm}kg"
            if snap.last_known_estimated_1rm is not None:
                sign = "+" if (snap.delta_vs_last or 0) >= 0 else ""
                base += (
                    f" (anterior {snap.last_known_estimated_1rm}kg, "
                    f"{sign}{snap.delta_vs_last}kg)"
                )
            else:
                base += " (sem 1RM anterior registrado)"
            parts.append(base)

    if ctx.notes:
        parts.append("\n## Notas das sessões")
        for n in ctx.notes:
            parts.append(f"- {n}")

    parts.append("\nGere o relatório seguindo a estrutura do system prompt. Não invente número.")
    return "\n".join(parts)


# ─── Persistence ──────────────────────────────────────────────────────────────


def _report_path(week_start: date_cls) -> Path:
    year, iso_week, _ = week_start.isocalendar()
    return REPORTS_DIR / str(year) / f"W{iso_week:02d}.md"


def _write_markdown_file(week_start: date_cls, week_end: date_cls, content: str) -> Path:
    p = _report_path(week_start)
    p.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Relatório semanal — {week_start.isoformat()} a {week_end.isoformat()}\n\n"
    )
    p.write_text(header + content, encoding="utf-8")
    return p


def _hash_context(ctx: WeeklyReportContext) -> str:
    blob = ctx.model_dump_json()
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ─── Service ──────────────────────────────────────────────────────────────────


class WeeklyReportService:
    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        self._router = llm_router or default_router

    def generate(
        self,
        db: DbSession,
        week_start: date_cls | None = None,
        week_end: date_cls | None = None,
    ) -> WeeklyReportResult:
        if week_start is None or week_end is None:
            ws, we = last_completed_week()
            week_start = week_start or ws
            week_end = week_end or we

        ctx = build_context(db, week_start, week_end)
        prompt = _render_prompt(ctx)

        result = self._router.complete(
            task_id="weekly_report",
            messages=[Message.user(prompt)],
            system=WEEKLY_REPORT_SYSTEM,
        )
        content = result.text

        file_path = _write_markdown_file(week_start, week_end, content)

        # Dedup: if an insight already exists for this exact window, update it.
        existing = (
            db.execute(
                select(Insight).where(
                    Insight.type == "weekly_report",
                    Insight.week_start == week_start,
                    Insight.week_end == week_end,
                )
            )
            .scalar_one_or_none()
        )
        if existing:
            existing.content_md = content
            existing.llm_provider = result.provider
            existing.llm_model = result.model
            existing.input_context_hash = _hash_context(ctx)
            existing.context_payload = json.loads(ctx.model_dump_json())
            existing.generated_at = datetime.now(UTC)
            insight = existing
        else:
            insight = Insight(
                type="weekly_report",
                target_date=None,
                week_start=week_start,
                week_end=week_end,
                content_md=content,
                llm_provider=result.provider,
                llm_model=result.model,
                input_context_hash=_hash_context(ctx),
                context_payload=json.loads(ctx.model_dump_json()),
            )
            db.add(insight)
        db.commit()
        db.refresh(insight)

        log.info(
            "weekly_report.generated",
            id=insight.id,
            week_start=str(week_start),
            week_end=str(week_end),
            path=str(file_path),
            tokens_in=result.input_tokens,
            tokens_out=result.output_tokens,
        )
        return WeeklyReportResult(
            id=insight.id,
            week_start=week_start,
            week_end=week_end,
            content_md=content,
            file_path=file_path,
        )


service = WeeklyReportService()
