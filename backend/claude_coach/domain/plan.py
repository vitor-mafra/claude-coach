"""Training plan schema — output of the PDF parser and input to briefing/reports.

Block taxonomy mirrors the Time Híbrido PDF semantics. Warmups are *suggestions*
attached to a template (not loggable blocks), so the loggable Block union is
strictly things with measurable execution.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from claude_coach.domain.calculations import HRZone
from claude_coach.domain.profile import Weekday


class ExerciseRef(BaseModel):
    """Reference to an exercise. `exercise_id` is set after catalog matching.

    `raw_name` is preserved from the PDF, so we can re-match if the catalog
    grows. `confidence` is filled by the matcher (0..1).
    """

    exercise_id: str | None = None
    raw_name: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class RestSpec(BaseModel):
    """Rest interval between sets."""

    seconds: int | None = None
    min_seconds: int | None = None
    max_seconds: int | None = None
    note: str | None = None


class WarmupSuggestion(BaseModel):
    """Pre-workout suggestion. Not logged; surfaced in briefing as 'preparação'."""

    description: str
    duration_min: int | None = None
    video_url: str | None = None


# ─── Loggable strength blocks ──────────────────────────────────────────────────


class MetaRepsBlock(BaseModel):
    """N sets × fixed reps, load is user-chosen at execution time."""

    kind: Literal["meta_reps"] = "meta_reps"
    exercise: ExerciseRef
    sets: int = Field(gt=0)
    reps: int = Field(gt=0)
    rest: RestSpec
    video_url: str | None = None


class PyramidBlock(BaseModel):
    """N sets with decreasing reps (e.g., 15-12-10-8); load usually progresses."""

    kind: Literal["pyramid"] = "pyramid"
    exercise: ExerciseRef
    reps_per_set: list[int] = Field(min_length=1)
    rest: RestSpec
    video_url: str | None = None


class BiSetExercise(BaseModel):
    exercise: ExerciseRef
    reps: int = Field(gt=0)


class BiSetBlock(BaseModel):
    """Two (or more) exercises alternated without rest between them."""

    kind: Literal["biset"] = "biset"
    rounds: int = Field(gt=0)
    exercises: list[BiSetExercise] = Field(min_length=2)
    rest: RestSpec
    video_urls: list[str] = Field(default_factory=list)


class DropsetBlock(BaseModel):
    """Initial set to failure; reduce weight; continue."""

    kind: Literal["dropset"] = "dropset"
    exercise: ExerciseRef
    sets: int = Field(gt=0)
    rest: RestSpec
    description: str | None = None
    video_url: str | None = None


class TabataBlock(BaseModel):
    kind: Literal["tabata"] = "tabata"
    rounds: int = Field(gt=0)  # how many full Tabata sequences
    description: str
    work_s: int = 20
    rest_s: int = 10
    rounds_per_set: int = 8
    rest: RestSpec | None = None
    video_url: str | None = None


# ─── Run blocks ────────────────────────────────────────────────────────────────


class RunSegment(BaseModel):
    """One segment: e.g., 6 reps × 500m @ Z5, or 6km @ Z3, or 5min @ Z1."""

    repeats: int = 1
    distance_km: float | None = None
    duration_min: float | None = None
    hr_zone: HRZone
    note: str | None = None  # "warmup", "recovery", "main set"


class IntervalRunBlock(BaseModel):
    kind: Literal["interval_run"] = "interval_run"
    name: str | None = None
    segments: list[RunSegment] = Field(min_length=1)
    video_url: str | None = None


class ContinuousRunBlock(BaseModel):
    kind: Literal["continuous_run"] = "continuous_run"
    name: str | None = None
    segments: list[RunSegment] = Field(min_length=1)
    video_url: str | None = None


class FartlekBlock(BaseModel):
    kind: Literal["fartlek"] = "fartlek"
    name: str | None = None
    segments: list[RunSegment] = Field(min_length=1)
    video_url: str | None = None


# ─── Discriminated union of loggable blocks ────────────────────────────────────

Block = Annotated[
    (
        MetaRepsBlock
        | PyramidBlock
        | BiSetBlock
        | DropsetBlock
        | TabataBlock
        | IntervalRunBlock
        | ContinuousRunBlock
        | FartlekBlock
    ),
    Field(discriminator="kind"),
]


WorkoutKind = Literal["strength", "run"]


class WorkoutTemplate(BaseModel):
    template_id: str  # "A", "B", "C", "D" for strength; "run-1", etc.
    name: str
    kind: WorkoutKind
    warmups: list[WarmupSuggestion] = Field(default_factory=list)
    blocks: list[Block]
    notes: str | None = None  # free-form trainer notes (e.g., focus, intent)


# Schedule maps each weekday to an ORDERED list of template_ids.
# Empty list = rest day. Multiple entries = double session (e.g., AM run + PM strength).
Schedule = dict[Weekday, list[str]]


class Plan(BaseModel):
    name: str
    level: str | None = None  # "Nível 1"
    goal: str | None = None  # "21km meia maratona"
    weeks_duration: int | None = None  # 1 for a single-week PDF
    templates: dict[str, WorkoutTemplate]  # keyed by template_id
    schedule: Schedule = Field(default_factory=dict)
    schedule_rationale: str | None = None  # LLM's explanation of the chosen schedule
    source_pdf: str | None = None
