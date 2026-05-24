from fastapi import APIRouter, HTTPException

from claude_coach.domain.profile import Profile
from claude_coach.services.profile import load_profile, save_profile

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=Profile | None)
def get_profile() -> Profile | None:
    return load_profile()


@router.put("", response_model=Profile)
def put_profile(profile: Profile) -> Profile:
    save_profile(profile)
    return profile


@router.get("/exists")
def profile_exists() -> dict:
    return {"exists": load_profile() is not None}


@router.delete("")
def delete_profile() -> dict:
    """Delete profile.yaml. Used by onboarding wizard reset."""
    from claude_coach.services.profile import PROFILE_PATH

    if not PROFILE_PATH.exists():
        raise HTTPException(404, "no profile to delete")
    PROFILE_PATH.unlink()
    return {"deleted": True}
