from fastapi import APIRouter, HTTPException

from claude_coach.domain.exercise import Exercise
from claude_coach.services.exercise_catalog import catalog

router = APIRouter(prefix="/exercises", tags=["exercises"])


@router.get("", response_model=list[Exercise])
def list_exercises() -> list[Exercise]:
    return catalog.all()


@router.get("/{exercise_id}", response_model=Exercise)
def get_exercise(exercise_id: str) -> Exercise:
    ex = catalog.by_id(exercise_id)
    if not ex:
        raise HTTPException(404, f"exercise {exercise_id!r} not found")
    return ex
