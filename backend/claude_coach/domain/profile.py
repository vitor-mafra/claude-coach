"""User profile schema (static identity + baseline)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
FCMaxSource = Literal["tanaka", "garmin", "tested"]
Sex = Literal["M", "F"]


class Profile(BaseModel):
    """Static profile, lives in data/profile.yaml committed to the repo.

    Dynamic data (weight, body comp over time) goes into the SQLite
    `body_metrics` table instead.
    """

    name: str
    birthdate: date
    sex: Sex
    height_cm: int = Field(gt=0, lt=300)
    fc_max_bpm: int = Field(gt=0, lt=260)
    fc_max_source: FCMaxSource = "tanaka"
    training_days: list[Weekday] = Field(default_factory=list)
    notes: str | None = None
