"""Pure calculations used across the app: HR zones, 1RM estimation."""

from typing import Literal

HRZone = Literal["Z1", "Z2", "Z3", "Z4", "Z5"]

_ZONE_BOUNDS: dict[HRZone, tuple[float, float]] = {
    "Z1": (0.50, 0.60),
    "Z2": (0.60, 0.70),
    "Z3": (0.70, 0.85),
    "Z4": (0.85, 0.95),
    "Z5": (0.95, 1.00),
}


def tanaka_fc_max(age_years: int) -> int:
    """Estimate max HR by Tanaka formula: 208 - 0.7 * age."""
    if age_years < 0:
        raise ValueError("age must be >= 0")
    return round(208 - 0.7 * age_years)


def epley_one_rm(weight_kg: float, reps: int) -> float:
    """Epley estimate: 1RM = weight × (1 + reps/30). 1RM == weight when reps == 1."""
    if reps < 1:
        raise ValueError("reps must be >= 1")
    if weight_kg <= 0:
        raise ValueError("weight must be > 0")
    if reps == 1:
        return float(weight_kg)
    return weight_kg * (1 + reps / 30)


def hr_zone_bounds(fc_max: int, zone: HRZone) -> tuple[int, int]:
    """Return (low_bpm, high_bpm) for a zone given the user's FCmax (% HRmax)."""
    low, high = _ZONE_BOUNDS[zone]
    return (round(fc_max * low), round(fc_max * high))


def hr_zone_bounds_from_floors(
    floors: dict[str, int], max_hr: int, zone: HRZone
) -> tuple[int, int]:
    """Bounds from Garmin-defined zone floors. Z5 high = max_hr."""
    order = ("Z1", "Z2", "Z3", "Z4", "Z5")
    if zone not in floors:
        return hr_zone_bounds(max_hr, zone)
    idx = order.index(zone)
    low = floors[zone]
    high = floors[order[idx + 1]] - 1 if idx < 4 and order[idx + 1] in floors else max_hr
    return (low, high)
