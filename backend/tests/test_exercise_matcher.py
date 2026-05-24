"""Tests use deterministic_match directly so they stay hermetic (no LLM calls)."""

from claude_coach.services.exercise_catalog import catalog
from claude_coach.services.exercise_matcher import deterministic_match


def test_match_exact_name():
    result = deterministic_match("Agachamento livre", catalog)
    assert result.exercise_id == "agachamento-livre"
    assert result.confidence == 1.0


def test_match_case_and_accent_insensitive():
    result = deterministic_match("agachamento LIVRE", catalog)
    assert result.exercise_id == "agachamento-livre"
    assert result.confidence == 1.0


def test_match_alias_from_pdf():
    # The PDF says "SUPINO RETO C/ HALTERES"; the canonical name is "Supino reto com halteres"
    result = deterministic_match("SUPINO RETO C/ HALTERES", catalog)
    assert result.exercise_id == "supino-reto-halteres"
    assert result.confidence >= 0.9


def test_match_terra_pdf_phrasing():
    result = deterministic_match("4X (15-12-10-8) TERRA DEADLIFT", catalog)
    # substring/token match — should land on deadlift
    assert result.exercise_id == "deadlift"
    assert result.confidence >= 0.6


def test_no_match_returns_none():
    result = deterministic_match("xyz inventado", catalog)
    assert result.exercise_id is None
    assert result.confidence == 0.0
