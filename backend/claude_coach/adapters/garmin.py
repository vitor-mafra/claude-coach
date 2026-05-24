"""GarminAdapter — wraps `garth`. Everything that touches Garmin Connect goes
through this module; nothing else imports `garth`.

Authentication: tokens are loaded from `settings.garmin_tokens_dir` (populated
by `scripts/garmin_login.py`). Adapter does not handle passwords or MFA.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date as date_cls, datetime, timedelta
from pathlib import Path
from typing import Any

import garth
import structlog

from claude_coach.config import settings

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class FetchedActivity:
    activity_id: int
    date: date_cls
    sport_type: str | None
    duration_s: int | None
    distance_km: float | None
    hr_avg: int | None
    hr_max: int | None
    training_effect_aerobic: float | None
    training_effect_anaerobic: float | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class FetchedDaily:
    date: date_cls
    sleep_score: int | None = None
    sleep_duration_min: int | None = None
    body_battery_start: int | None = None
    body_battery_end: int | None = None
    stress_avg: int | None = None
    hrv_avg: float | None = None
    training_readiness: int | None = None
    valid_as_of_timestamp: datetime | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class FetchedVO2Max:
    date: date_cls
    vo2_max: float
    fitness_age: int | None = None


@dataclass(frozen=True)
class FetchedWeight:
    date: date_cls
    weight_kg: float | None
    body_fat_pct: float | None
    lean_mass_kg: float | None


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime | date_cls):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {type(obj).__name__}")


def _to_dict(obj: Any) -> dict[str, Any]:
    """Coerce a garth dataclass/object into a JSON-safe dict.

    Dates and datetimes are serialized as ISO strings so SQLAlchemy's JSON
    column can persist them without TypeError.
    """
    if obj is None:
        return {}
    if is_dataclass(obj):
        raw = asdict(obj)
    elif hasattr(obj, "__dict__"):
        raw = {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    else:
        raw = {"value": obj}
    return json.loads(json.dumps(raw, default=_json_default))


class GarminAuthError(RuntimeError):
    pass


class GarminAdapter:
    """High-level Garmin reader. All datetimes returned are in user-local Garmin time."""

    def __init__(self, tokens_dir: Path | None = None) -> None:
        self._tokens_dir = tokens_dir or settings.garmin_tokens_dir
        self._loaded = False

    def ensure_session(self) -> None:
        if self._loaded:
            return
        if not self._tokens_dir.exists():
            raise GarminAuthError(
                f"No Garmin tokens at {self._tokens_dir}. Run `scripts/garmin_login.py` first."
            )
        try:
            garth.resume(str(self._tokens_dir))
        except Exception as exc:  # garth raises various concrete errors
            raise GarminAuthError(f"Failed to resume Garmin session: {exc}") from exc
        self._loaded = True

    # ----- Activities -----

    def fetch_activities(self, day: date_cls, *, lookback: int = 30) -> list[FetchedActivity]:
        """Pull recent activities and filter to the given local date.

        garth's Activity.list returns most-recent-first; `lookback` controls how
        far back we ask for in case the user backfills several activities on a
        single day."""
        self.ensure_session()
        items = garth.Activity.list(limit=lookback)
        out: list[FetchedActivity] = []
        for a in items:
            try:
                start_local = a.start_time_local
                if isinstance(start_local, str):
                    start_local = datetime.fromisoformat(start_local)
                a_date = start_local.date() if isinstance(start_local, datetime) else None
            except Exception:
                a_date = None
            if a_date != day:
                continue
            raw = _to_dict(a)
            sport = (
                a.activity_type.get("typeKey")
                if isinstance(a.activity_type, dict)
                else getattr(a.activity_type, "type_key", None)
            )
            distance_m = a.distance or 0.0
            te_aero = raw.get("aerobic_training_effect") or raw.get("aerobicTrainingEffect")
            te_anaero = raw.get("anaerobic_training_effect") or raw.get("anaerobicTrainingEffect")
            out.append(
                FetchedActivity(
                    activity_id=int(a.activity_id),
                    date=a_date,
                    sport_type=sport,
                    duration_s=int(a.duration) if a.duration else None,
                    distance_km=round(distance_m / 1000.0, 3) if distance_m else None,
                    hr_avg=int(a.average_hr) if a.average_hr else None,
                    hr_max=int(a.max_hr) if a.max_hr else None,
                    training_effect_aerobic=te_aero,
                    training_effect_anaerobic=te_anaero,
                    raw=raw,
                )
            )
        return out

    # ----- Daily metrics -----

    def fetch_daily(self, day: date_cls) -> FetchedDaily:
        """Aggregates sleep / stress / body battery / HRV / training readiness for `day`."""
        self.ensure_session()
        raw: dict[str, Any] = {}

        sleep_score: int | None = None
        sleep_duration_min: int | None = None
        try:
            sleep = garth.SleepData.get(day)
            if sleep and sleep.daily_sleep_dto:
                dto = sleep.daily_sleep_dto
                raw["sleep"] = _to_dict(dto)
                scores = getattr(dto, "sleep_scores", None)
                overall = getattr(scores, "overall", None) if scores is not None else None
                if isinstance(overall, dict):
                    sleep_score = overall.get("value")
                elif overall is not None:
                    sleep_score = getattr(overall, "value", None)
                seconds = getattr(dto, "sleep_time_seconds", None)
                if seconds:
                    sleep_duration_min = int(seconds // 60)
        except Exception as exc:
            log.warning("garmin.sleep.fail", date=str(day), error=str(exc))

        bb_start: int | None = None
        bb_end: int | None = None
        stress_avg: int | None = None
        try:
            bb = garth.DailyBodyBatteryStress.get(day)
            if bb:
                raw["body_battery_stress"] = _to_dict(bb)
                stress_avg = getattr(bb, "avg_stress_level", None)
                series = getattr(bb, "body_battery_values_array", None) or []
                # series items look like [ts, status, level, ...]; pick first/last numeric level
                levels = [row[2] for row in series if len(row) >= 3 and isinstance(row[2], int)]
                if levels:
                    bb_start = levels[0]
                    bb_end = levels[-1]
        except Exception as exc:
            log.warning("garmin.body_battery.fail", date=str(day), error=str(exc))

        hrv_avg: float | None = None
        try:
            hrv = garth.HRVData.get(day)
            if hrv:
                raw["hrv"] = _to_dict(hrv)
                summary = hrv.hrv_summary
                weekly = (
                    summary.get("weeklyAvg")
                    if isinstance(summary, dict)
                    else getattr(summary, "weekly_avg", None)
                )
                last_night = (
                    summary.get("lastNightAvg")
                    if isinstance(summary, dict)
                    else getattr(summary, "last_night_avg", None)
                )
                hrv_avg = last_night if last_night is not None else weekly
        except Exception as exc:
            log.warning("garmin.hrv.fail", date=str(day), error=str(exc))

        readiness: int | None = None
        valid_ts: datetime | None = None
        try:
            tr_data = garth.TrainingReadinessData.get(day)
            tr = tr_data[0] if isinstance(tr_data, list) and tr_data else tr_data
            if tr and not isinstance(tr, list):
                raw["training_readiness"] = _to_dict(tr)
                readiness = getattr(tr, "score", None)
                ts = getattr(tr, "timestamp", None)
                if isinstance(ts, str):
                    try:
                        valid_ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        valid_ts = None
                elif isinstance(ts, datetime):
                    valid_ts = ts
        except Exception as exc:
            log.warning("garmin.readiness.fail", date=str(day), error=str(exc))

        return FetchedDaily(
            date=day,
            sleep_score=sleep_score,
            sleep_duration_min=sleep_duration_min,
            body_battery_start=bb_start,
            body_battery_end=bb_end,
            stress_avg=stress_avg,
            hrv_avg=hrv_avg,
            training_readiness=readiness,
            valid_as_of_timestamp=valid_ts,
            raw=raw or None,
        )

    # ----- VO2 max -----

    def fetch_latest_vo2_max(self, *, days_back: int = 180) -> FetchedVO2Max | None:
        """Hit the maxmet daily endpoint and return the most recent reading."""
        self.ensure_session()
        end = datetime.now(UTC).date()
        start = end - timedelta(days=days_back)
        try:
            data = garth.connectapi(
                f"/metrics-service/metrics/maxmet/daily/{start}/{end}"
            )
        except Exception as exc:
            log.warning("garmin.vo2_max.fail", error=str(exc))
            return None
        if not isinstance(data, list) or not data:
            return None
        # Pick the most recent entry that has a vo2MaxValue.
        candidates: list[FetchedVO2Max] = []
        for item in data:
            gen = item.get("generic") if isinstance(item, dict) else None
            if not isinstance(gen, dict):
                continue
            val = gen.get("vo2MaxPreciseValue") or gen.get("vo2MaxValue")
            cal = gen.get("calendarDate")
            if val is None or not cal:
                continue
            try:
                d = datetime.strptime(cal, "%Y-%m-%d").date()
            except ValueError:
                continue
            candidates.append(
                FetchedVO2Max(date=d, vo2_max=float(val), fitness_age=gen.get("fitnessAge"))
            )
        if not candidates:
            return None
        candidates.sort(key=lambda x: x.date, reverse=True)
        return candidates[0]

    # ----- Weight -----

    def fetch_weight(self, day: date_cls) -> FetchedWeight | None:
        self.ensure_session()
        try:
            w = garth.WeightData.get(day)
        except Exception as exc:
            log.warning("garmin.weight.fail", date=str(day), error=str(exc))
            return None
        if not w or not getattr(w, "weight", None):
            return None
        weight_g = w.weight  # garth returns grams
        weight_kg = round(weight_g / 1000.0, 2) if weight_g else None
        body_fat = getattr(w, "body_fat", None)
        muscle_g = getattr(w, "muscle_mass", None)
        lean_kg = round(muscle_g / 1000.0, 2) if muscle_g else None
        return FetchedWeight(
            date=day,
            weight_kg=weight_kg,
            body_fat_pct=body_fat,
            lean_mass_kg=lean_kg,
        )


adapter = GarminAdapter()
