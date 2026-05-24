"""Canonical exercise catalog schema."""

from typing import Literal

from pydantic import BaseModel, Field

MuscleGroup = Literal[
    "quads",
    "hamstrings",
    "glutes",
    "calves",
    "adductors",
    "abductors",
    "chest",
    "back",
    "shoulders",
    "biceps",
    "triceps",
    "forearms",
    "abs",
    "core",
    "lower_back",
    "full_body",
]

Equipment = Literal[
    "barbell",
    "dumbbell",
    "machine",
    "cable",
    "bodyweight",
    "kettlebell",
    "smith",
    "band",
    "other",
]


class Exercise(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str  # canonical Portuguese display name
    aliases: list[str] = Field(default_factory=list)
    primary_muscle_group: MuscleGroup
    secondary_muscle_groups: list[MuscleGroup] = Field(default_factory=list)
    equipment: Equipment
    video_url: str | None = None
    notes: str | None = None
