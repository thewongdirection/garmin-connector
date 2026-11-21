"""Normalised, unit-labelled records returned by the tools.

Raw Garmin payloads are not passed through: each parser picks the fields that
matter and converts units, and a missing value stays None (never 0).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

Record = dict[str, Any]


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _int(value: Any) -> int | None:
    number = _num(value)
    return None if number is None else round(number)


def _minutes(seconds: Any) -> float | None:
    number = _num(seconds)
    return None if number is None else round(number / 60, 1)


def _minutes_from_ms(millis: Any) -> float | None:
    number = _num(millis)
    return None if number is None else round(number / 60000, 1)


def _dict(value: Any) -> Record:
    return value if isinstance(value, dict) else {}


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


class SleepNight(BaseModel):
    """One night's sleep. `date` is the calendar date Garmin assigns (the wake-up day)."""

    date: str
    sleep_score: int | None = Field(None, description="Garmin overall sleep score, 0-100")
    sleep_subscores: dict[str, int] = Field(default_factory=dict)
    total_sleep_min: float | None = None
    deep_min: float | None = None
    light_min: float | None = None
    rem_min: float | None = None
    awake_min: float | None = None
    awake_count: int | None = None
    avg_sleep_hr_bpm: int | None = None
    avg_respiration_brpm: float | None = None
    avg_spo2_pct: float | None = None
    avg_sleep_stress: float | None = None
    sleep_need_min: int | None = None

    @classmethod
    def from_api(cls, raw: Record) -> SleepNight:
        scores = _dict(raw.get("sleepScores"))
        subscores = {
            str(name): int(value)
            for name, item in scores.items()
            if (value := _int(_dict(item).get("value"))) is not None
        }
        overall = subscores.get("overall")
        need = _dict(raw.get("sleepNeed"))
        return cls(
            date=str(raw.get("calendarDate", "")),
            sleep_score=overall,
            sleep_subscores={k: v for k, v in subscores.items() if k != "overall"},
            total_sleep_min=_minutes(raw.get("sleepTimeSeconds")),
            deep_min=_minutes(raw.get("deepSleepSeconds")),
            light_min=_minutes(raw.get("lightSleepSeconds")),
            rem_min=_minutes(raw.get("remSleepSeconds")),
            awake_min=_minutes(raw.get("awakeSleepSeconds")),
            awake_count=_int(raw.get("awakeCount")),
            avg_sleep_hr_bpm=_int(raw.get("avgHeartRate")),
            avg_respiration_brpm=_num(raw.get("averageRespirationValue")),
            avg_spo2_pct=_num(raw.get("averageSpO2Value")),
            avg_sleep_stress=_num(raw.get("avgSleepStress")),
            sleep_need_min=_int(need.get("actual")),
        )


class HrvNight(BaseModel):
    date: str
    last_night_avg_ms: int | None = None
    last_night_5min_high_ms: int | None = None
    weekly_avg_ms: int | None = None
    baseline_balanced_low_ms: int | None = None
    baseline_balanced_upper_ms: int | None = None
    status: str | None = Field(
        None, description="Garmin HRV status, e.g. BALANCED, UNBALANCED, LOW"
    )

    @classmethod
    def from_api(cls, raw: Record) -> HrvNight:
        baseline = _dict(raw.get("baseline"))
        status = _str(raw.get("status"))
        return cls(
            date=str(raw.get("calendarDate", "")),
            last_night_avg_ms=_int(raw.get("lastNightAvg")),
            last_night_5min_high_ms=_int(raw.get("lastNight5MinHigh")),
            weekly_avg_ms=_int(raw.get("weeklyAvg")),
            baseline_balanced_low_ms=_int(baseline.get("balancedLow")),
            baseline_balanced_upper_ms=_int(baseline.get("balancedUpper")),
            status=None if status == "NONE" else status,
        )


class DailyWellness(BaseModel):
    """All-day wellness for one calendar date."""

    date: str
    resting_hr_bpm: int | None = None
    min_hr_bpm: int | None = None
    max_hr_bpm: int | None = None
    stress_avg: int | None = Field(None, description="Garmin stress level, 0-100")
    stress_max: int | None = None
    stress_qualifier: str | None = None
    rest_stress_min: float | None = None
    low_stress_min: float | None = None
    medium_stress_min: float | None = None
    high_stress_min: float | None = None
    body_battery_high: int | None = None
    body_battery_low: int | None = None
    body_battery_charged: int | None = None
    body_battery_drained: int | None = None
    body_battery_end_of_day: int | None = None
    respiration_avg_brpm: float | None = None
    spo2_avg_pct: float | None = None
    intensity_min_moderate: int | None = None
    intensity_min_vigorous: int | None = None
    steps: int | None = None

    @classmethod
    def from_api(cls, raw: Record) -> DailyWellness:
        hr = _dict(raw.get("heartRate"))
        stress = _dict(raw.get("stress"))
        battery = _dict(raw.get("bodyBattery"))
        intensity = _dict(raw.get("intensityMinutes"))
        return cls(
            date=str(raw.get("calendarDate", "")),
            resting_hr_bpm=_int(hr.get("restingValue")),
            min_hr_bpm=_int(hr.get("minValue")),
            max_hr_bpm=_int(hr.get("maxValue")),
            stress_avg=_int(stress.get("avgLevel")),
            stress_max=_int(stress.get("maxLevel")),
            stress_qualifier=_str(stress.get("qualifier")),
            rest_stress_min=_minutes_from_ms(stress.get("restDurationInMillis")),
            low_stress_min=_minutes_from_ms(stress.get("lowStressDurationInMillis")),
            medium_stress_min=_minutes_from_ms(stress.get("mediumStressDurationInMillis")),
            high_stress_min=_minutes_from_ms(stress.get("highStressDurationInMillis")),
            body_battery_high=_int(battery.get("maxValue")),
            body_battery_low=_int(battery.get("minValue")),
            body_battery_charged=_int(battery.get("chargedValue")),
            body_battery_drained=_int(battery.get("drainedValue")),
            body_battery_end_of_day=_int(battery.get("endOfDayValue")),
            respiration_avg_brpm=_num(_dict(raw.get("respiration")).get("avgValue")),
            spo2_avg_pct=_num(_dict(raw.get("pulseOx")).get("avgValue")),
            intensity_min_moderate=_int(intensity.get("moderate")),
            intensity_min_vigorous=_int(intensity.get("vigorous")),
            steps=_steps(raw.get("movement")),
        )


def _steps(movement: Any) -> int | None:
    """Garmin's schema shows `movement` as a JSON string; accept a dict too."""
    if isinstance(movement, str):
        try:
            movement = json.loads(movement)
        except ValueError:
            return None
    return _int(_dict(_dict(movement).get("steps")).get("value"))


class Vo2MaxReading(BaseModel):
    date: str
    sport: str = Field(description="generic (running/walking), cycling, or rowing")
    vo2max: float

    @classmethod
    def from_api(cls, raw: Record) -> list[Vo2MaxReading]:
        readings = []
        for sport, item in raw.items():
            entry = _dict(item)
            value = _num(entry.get("vo2MaxPreciseValue")) or _num(entry.get("vo2MaxValue"))
            if value is not None and value > 0 and entry.get("calendarDate"):
                readings.append(
                    cls(date=str(entry["calendarDate"]), sport=str(sport), vo2max=round(value, 1))
                )
        return readings
