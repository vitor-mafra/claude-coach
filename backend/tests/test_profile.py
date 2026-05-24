from datetime import date
from pathlib import Path

from claude_coach.domain.profile import Profile
from claude_coach.services.profile import load_profile, save_profile


def test_save_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "profile.yaml"
    p = Profile(
        name="Test",
        birthdate=date(2000, 1, 1),
        sex="M",
        height_cm=180,
        fc_max_bpm=192,
        fc_max_source="tanaka",
        training_days=["mon", "tue", "wed", "thu", "fri"],
    )
    save_profile(p, path=path)
    loaded = load_profile(path=path)
    assert loaded == p


def test_load_missing_returns_none(tmp_path: Path):
    assert load_profile(path=tmp_path / "nope.yaml") is None
