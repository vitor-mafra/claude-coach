"""Profile load/save against data/profile.yaml (committed to git)."""

from pathlib import Path

import yaml

from claude_coach.config import REPO_ROOT
from claude_coach.domain.profile import Profile

PROFILE_PATH: Path = REPO_ROOT / "data" / "profile.yaml"


def load_profile(path: Path = PROFILE_PATH) -> Profile | None:
    if not path.exists():
        return None
    with path.open() as f:
        data = yaml.safe_load(f)
    if not data:
        return None
    return Profile.model_validate(data)


def save_profile(profile: Profile, path: Path = PROFILE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump(
            profile.model_dump(mode="json"),
            f,
            allow_unicode=True,
            sort_keys=False,
        )
