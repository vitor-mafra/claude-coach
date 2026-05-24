"""Round-trip a hand-crafted Plan through validation to lock the schema in."""

from claude_coach.domain.plan import (
    BiSetBlock,
    BiSetExercise,
    ContinuousRunBlock,
    DropsetBlock,
    ExerciseRef,
    FartlekBlock,
    IntervalRunBlock,
    MetaRepsBlock,
    Plan,
    PyramidBlock,
    RestSpec,
    RunSegment,
    TabataBlock,
    WarmupSuggestion,
    WorkoutTemplate,
)


def _treino_a() -> WorkoutTemplate:
    return WorkoutTemplate(
        template_id="A",
        name="Membros inferiores + abs",
        kind="strength",
        warmups=[
            WarmupSuggestion(description="Flexibilidade e mobilidade inferiores"),
            WarmupSuggestion(description="4×15 agachamento c/ peso do corpo", duration_min=5),
        ],
        blocks=[
            MetaRepsBlock(
                exercise=ExerciseRef(raw_name="Agachamento livre"),
                sets=4,
                reps=15,
                rest=RestSpec(seconds=60),
            ),
            PyramidBlock(
                exercise=ExerciseRef(raw_name="Terra deadlift"),
                reps_per_set=[15, 12, 10, 8],
                rest=RestSpec(min_seconds=60, max_seconds=180),
            ),
            BiSetBlock(
                rounds=4,
                exercises=[
                    BiSetExercise(exercise=ExerciseRef(raw_name="Cadeira abdutora"), reps=15),
                    BiSetExercise(exercise=ExerciseRef(raw_name="Panturrilha em pé"), reps=15),
                ],
                rest=RestSpec(seconds=45),
            ),
            TabataBlock(rounds=2, description="Sequência tabata abdominal"),
        ],
    )


def _run_tue() -> WorkoutTemplate:
    return WorkoutTemplate(
        template_id="run-tue",
        name="Intervalado 500m forte",
        kind="run",
        blocks=[
            IntervalRunBlock(
                name="Intervalado 500m forte",
                segments=[
                    RunSegment(distance_km=3, hr_zone="Z2", note="warmup"),
                    RunSegment(repeats=6, distance_km=0.5, hr_zone="Z5", note="main"),
                    RunSegment(duration_min=2, hr_zone="Z1", note="recovery"),
                    RunSegment(duration_min=5, hr_zone="Z1", note="cooldown"),
                ],
            ),
        ],
    )


def test_plan_round_trip_with_double_session_day():
    plan = Plan(
        name="Desafio Atleta Híbrido — Nível 1",
        level="Nível 1",
        goal="21km meia maratona",
        weeks_duration=1,
        templates={"A": _treino_a(), "run-tue": _run_tue()},
        schedule={
            "mon": [],
            "tue": ["run-tue", "A"],  # double session day
            "wed": [],
            "thu": [],
            "fri": [],
            "sat": [],
            "sun": [],
        },
        schedule_rationale="Test rationale.",
    )
    dumped = plan.model_dump(mode="json")
    restored = Plan.model_validate(dumped)
    assert restored == plan
    assert restored.schedule["tue"] == ["run-tue", "A"]


def test_block_discriminator_picks_right_subtype():
    plan = Plan(
        name="X",
        templates={
            "X": WorkoutTemplate(
                template_id="X",
                name="X",
                kind="strength",
                blocks=[
                    MetaRepsBlock(
                        exercise=ExerciseRef(raw_name="ex"),
                        sets=3,
                        reps=10,
                        rest=RestSpec(seconds=60),
                    ),
                    DropsetBlock(
                        exercise=ExerciseRef(raw_name="ex"),
                        sets=4,
                        rest=RestSpec(seconds=45),
                    ),
                    ContinuousRunBlock(
                        segments=[RunSegment(distance_km=6, hr_zone="Z3")]
                    ),
                    FartlekBlock(segments=[RunSegment(repeats=3, distance_km=1, hr_zone="Z3")]),
                ],
            )
        },
    )
    dumped = plan.model_dump(mode="json")
    restored = Plan.model_validate(dumped)
    kinds = [b.kind for b in restored.templates["X"].blocks]
    assert kinds == ["meta_reps", "dropset", "continuous_run", "fartlek"]
