"""A simple recovery snapshot built from Garmin data.

This is the connector's own estimate, not Garmin's Training Readiness, which the
Personal API does not expose. Thresholds are deliberately plain so they are easy
to read and tune.
"""

from __future__ import annotations

from statistics import mean
from typing import Literal

from pydantic import BaseModel

from .models import DailyWellness, HrvNight, SleepNight

Rating = Literal["green", "amber", "red"]
Overall = Literal["green", "amber", "red", "unknown"]

DISCLAIMER = (
    "Connector's own estimate from sleep, HRV, Body Battery, resting heart rate and "
    "stress. Not Garmin's Training Readiness."
)

SLEEP_GREEN, SLEEP_AMBER = 80, 60
BATTERY_GREEN, BATTERY_AMBER = 70, 40
RHR_GREEN_DELTA, RHR_AMBER_DELTA = 2.0, 5.0
STRESS_GREEN, STRESS_AMBER = 25, 50
MIN_RHR_HISTORY = 3

_HRV_STATUS: dict[str, Rating] = {
    "BALANCED": "green",
    "UNBALANCED": "amber",
    "LOW": "red",
    "POOR": "red",
}


class Signal(BaseModel):
    name: str
    value: float | str
    unit: str
    rating: Rating
    note: str


class RecoverySnapshot(BaseModel):
    date: str
    overall: Overall
    signals: list[Signal]
    missing: list[str]
    note: str = DISCLAIMER


def _band_high_is_good(value: float, green: float, amber: float) -> Rating:
    if value >= green:
        return "green"
    return "amber" if value >= amber else "red"


def _band_low_is_good(value: float, green: float, amber: float) -> Rating:
    if value <= green:
        return "green"
    return "amber" if value <= amber else "red"


def sleep_signal(night: SleepNight | None) -> Signal | None:
    if night is None or night.sleep_score is None:
        return None
    return Signal(
        name="sleep_score",
        value=night.sleep_score,
        unit="score 0-100",
        rating=_band_high_is_good(night.sleep_score, SLEEP_GREEN, SLEEP_AMBER),
        note=f"{night.total_sleep_min or 0:.0f} min asleep",
    )


def hrv_signal(hrv: HrvNight | None) -> Signal | None:
    if hrv is None:
        return None
    if hrv.status in _HRV_STATUS:
        return Signal(
            name="hrv",
            value=hrv.last_night_avg_ms if hrv.last_night_avg_ms is not None else hrv.status,
            unit="ms" if hrv.last_night_avg_ms is not None else "status",
            rating=_HRV_STATUS[hrv.status],
            note=f"Garmin status {hrv.status}",
        )
    low, avg = hrv.baseline_balanced_low_ms, hrv.last_night_avg_ms
    if low is None or avg is None:
        return None
    return Signal(
        name="hrv",
        value=avg,
        unit="ms",
        rating="green" if avg >= low else "amber",
        note=f"baseline low {low} ms",
    )


def body_battery_signal(day: DailyWellness | None) -> Signal | None:
    if day is None or day.body_battery_high is None:
        return None
    return Signal(
        name="body_battery",
        value=day.body_battery_high,
        unit="0-100",
        rating=_band_high_is_good(day.body_battery_high, BATTERY_GREEN, BATTERY_AMBER),
        note="highest so far today (usually the wake-up level)",
    )


def resting_hr_signal(day: DailyWellness | None, history: list[DailyWellness]) -> Signal | None:
    if day is None or day.resting_hr_bpm is None:
        return None
    previous = [d.resting_hr_bpm for d in history if d.resting_hr_bpm is not None]
    if len(previous) < MIN_RHR_HISTORY:
        return None
    baseline = mean(previous)
    delta = day.resting_hr_bpm - baseline
    return Signal(
        name="resting_hr",
        value=day.resting_hr_bpm,
        unit="bpm",
        rating=_band_low_is_good(delta, RHR_GREEN_DELTA, RHR_AMBER_DELTA),
        note=f"{delta:+.1f} bpm vs {len(previous)}-day average {baseline:.1f}",
    )


def stress_signal(yesterday: DailyWellness | None) -> Signal | None:
    if yesterday is None or yesterday.stress_avg is None:
        return None
    return Signal(
        name="yesterday_stress",
        value=yesterday.stress_avg,
        unit="avg 0-100",
        rating=_band_low_is_good(yesterday.stress_avg, STRESS_GREEN, STRESS_AMBER),
        note=f"average stress on {yesterday.date}",
    )


def overall_rating(signals: list[Signal]) -> Overall:
    if not signals:
        return "unknown"
    reds = sum(s.rating == "red" for s in signals)
    ambers = sum(s.rating == "amber" for s in signals)
    if reds >= 2:
        return "red"
    if reds == 1 or ambers >= 2:
        return "amber"
    return "green"


def build_snapshot(
    day: str,
    night: SleepNight | None,
    hrv: HrvNight | None,
    today_wellness: DailyWellness | None,
    yesterday_wellness: DailyWellness | None,
    rhr_history: list[DailyWellness],
) -> RecoverySnapshot:
    candidates = {
        "sleep_score": sleep_signal(night),
        "hrv": hrv_signal(hrv),
        "body_battery": body_battery_signal(today_wellness),
        "resting_hr": resting_hr_signal(today_wellness, rhr_history),
        "yesterday_stress": stress_signal(yesterday_wellness),
    }
    signals = [s for s in candidates.values() if s is not None]
    missing = [name for name, s in candidates.items() if s is None]
    return RecoverySnapshot(
        date=day, overall=overall_rating(signals), signals=signals, missing=missing
    )
