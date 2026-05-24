"""Loads canonical exercise catalog from data/exercises/*.yaml."""

from pathlib import Path

import yaml

from claude_coach.config import REPO_ROOT
from claude_coach.domain.exercise import Exercise

CATALOG_DIR: Path = REPO_ROOT / "data" / "exercises"


class ExerciseCatalog:
    def __init__(self, directory: Path = CATALOG_DIR) -> None:
        self.directory = directory
        self._by_id: dict[str, Exercise] | None = None

    def _load(self) -> dict[str, Exercise]:
        if self._by_id is not None:
            return self._by_id
        result: dict[str, Exercise] = {}
        if self.directory.exists():
            for yaml_path in sorted(self.directory.glob("*.yaml")):
                with yaml_path.open() as f:
                    data = yaml.safe_load(f)
                exercise = Exercise.model_validate(data)
                if exercise.id in result:
                    raise ValueError(f"Duplicate exercise id: {exercise.id} in {yaml_path}")
                result[exercise.id] = exercise
        self._by_id = result
        return result

    def all(self) -> list[Exercise]:
        return list(self._load().values())

    def by_id(self, exercise_id: str) -> Exercise | None:
        return self._load().get(exercise_id)

    def reload(self) -> None:
        self._by_id = None

    def save(self, exercise: Exercise) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        out = self.directory / f"{exercise.id}.yaml"
        with out.open("w") as f:
            yaml.safe_dump(
                exercise.model_dump(mode="json"),
                f,
                allow_unicode=True,
                sort_keys=False,
            )
        self.reload()
        return out


catalog = ExerciseCatalog()
