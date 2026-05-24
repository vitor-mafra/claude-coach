import pytest

from claude_coach.domain.calculations import epley_one_rm, hr_zone_bounds, tanaka_fc_max


def test_tanaka_known_values():
    # 208 - 0.7 * 26 = 189.8 → 190
    assert tanaka_fc_max(26) == 190
    # 208 - 0.7 * 30 = 187.0
    assert tanaka_fc_max(30) == 187
    # 208 - 0.7 * 50 = 173.0
    assert tanaka_fc_max(50) == 173


def test_tanaka_negative_age_raises():
    with pytest.raises(ValueError):
        tanaka_fc_max(-1)


def test_epley_one_rep_equals_weight():
    assert epley_one_rm(100, 1) == 100.0


def test_epley_multi_rep_estimate():
    # 80 * (1 + 5/30) = 93.333...
    assert epley_one_rm(80, 5) == pytest.approx(93.333, abs=0.01)


def test_epley_invalid_reps_raises():
    with pytest.raises(ValueError):
        epley_one_rm(100, 0)


def test_epley_invalid_weight_raises():
    with pytest.raises(ValueError):
        epley_one_rm(0, 5)


def test_hr_zone_bounds_z1_z5():
    # fc_max=190 → 190*0.95 = 180.5 (banker's rounding → 180)
    assert hr_zone_bounds(190, "Z1") == (95, 114)
    assert hr_zone_bounds(190, "Z3") == (133, 162)
    assert hr_zone_bounds(190, "Z5") == (180, 190)
