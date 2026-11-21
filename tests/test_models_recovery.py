from datetime import date

from garmin_connector.models import DailyWellness, HrvNight, SleepNight, Vo2MaxReading
from garmin_connector.recovery import build_snapshot, overall_rating

from .conftest import daily_record, hrv_record, sleep_record

DAY = date(2026, 11, 20)


def test_sleep_night_normalises_units_and_scores() -> None:
    night = SleepNight.from_api(sleep_record(DAY))
    assert night.date == "2026-11-20"
    assert night.sleep_score == 82
    assert night.sleep_subscores == {"remPercentage": 18}
    assert night.total_sleep_min == 420.0
    assert night.deep_min == 64.0
    assert night.awake_count == 2
    assert night.sleep_need_min == 480


def test_missing_values_stay_none_not_zero() -> None:
    night = SleepNight.from_api({"calendarDate": "2026-11-20", "sleepScores": None})
    assert night.sleep_score is None
    assert night.total_sleep_min is None
    assert night.sleep_subscores == {}
    day = DailyWellness.from_api({"calendarDate": "2026-11-20", "heartRate": "oops"})
    assert day.resting_hr_bpm is None
    assert day.steps is None


def test_booleans_are_not_numbers() -> None:
    assert SleepNight.from_api({"calendarDate": "x", "awakeCount": True}).awake_count is None


def test_hrv_status_none_becomes_null() -> None:
    hrv = HrvNight.from_api(hrv_record(DAY, status="NONE"))
    assert hrv.status is None
    assert hrv.baseline_balanced_low_ms == 44


def test_daily_wellness_parses_nested_and_movement_string() -> None:
    day = DailyWellness.from_api(daily_record(DAY))
    assert day.resting_hr_bpm == 57
    assert day.body_battery_high == 82
    assert day.stress_avg == 27
    assert day.low_stress_min == 210.0
    assert day.steps == 6786
    assert day.spo2_avg_pct == 95.0


def test_daily_wellness_movement_as_dict_or_malformed() -> None:
    raw = daily_record(DAY)
    raw["movement"] = {"steps": {"value": 1234}}
    assert DailyWellness.from_api(raw).steps == 1234
    raw["movement"] = '{"steps":{"value",5000}}'  # malformed, as in Garmin's own example
    assert DailyWellness.from_api(raw).steps is None


def test_vo2max_reads_each_sport_and_skips_empty() -> None:
    raw = {
        "generic": {"calendarDate": "2026-11-20", "vo2MaxPreciseValue": 41.6, "vo2MaxValue": 42},
        "cycling": {"calendarDate": "2026-11-20", "vo2MaxPreciseValue": 0, "vo2MaxValue": 0},
        "rowing": None,
    }
    readings = Vo2MaxReading.from_api(raw)
    assert [(r.sport, r.vo2max) for r in readings] == [("generic", 41.6)]


def _history(resting: int, days: int = 7) -> list[DailyWellness]:
    return [
        DailyWellness.from_api(daily_record(date(2026, 11, 10 + i), resting=resting))
        for i in range(days)
    ]


def test_snapshot_all_green() -> None:
    snap = build_snapshot(
        day="2026-11-20",
        night=SleepNight.from_api(sleep_record(DAY, score=85)),
        hrv=HrvNight.from_api(hrv_record(DAY)),
        today_wellness=DailyWellness.from_api(daily_record(DAY, resting=56, battery_high=80)),
        yesterday_wellness=DailyWellness.from_api(daily_record(DAY, stress=20)),
        rhr_history=_history(56),
    )
    assert snap.overall == "green"
    assert snap.missing == []
    assert {s.name: s.rating for s in snap.signals} == {
        "sleep_score": "green",
        "hrv": "green",
        "body_battery": "green",
        "resting_hr": "green",
        "yesterday_stress": "green",
    }
    assert "Not Garmin's Training Readiness" in snap.note


def test_snapshot_thresholds_and_overall() -> None:
    snap = build_snapshot(
        day="2026-11-20",
        night=SleepNight.from_api(sleep_record(DAY, score=55)),
        hrv=HrvNight.from_api(hrv_record(DAY, status="UNBALANCED")),
        today_wellness=DailyWellness.from_api(daily_record(DAY, resting=63, battery_high=35)),
        yesterday_wellness=DailyWellness.from_api(daily_record(DAY, stress=45)),
        rhr_history=_history(57),
    )
    ratings = {s.name: s.rating for s in snap.signals}
    assert ratings == {
        "sleep_score": "red",
        "hrv": "amber",
        "body_battery": "red",
        "resting_hr": "red",
        "yesterday_stress": "amber",
    }
    assert snap.overall == "red"


def test_snapshot_handles_missing_data() -> None:
    snap = build_snapshot("2026-11-20", None, None, None, None, [])
    assert snap.overall == "unknown"
    assert set(snap.missing) == {
        "sleep_score",
        "hrv",
        "body_battery",
        "resting_hr",
        "yesterday_stress",
    }


def test_resting_hr_needs_enough_history() -> None:
    snap = build_snapshot(
        "2026-11-20",
        None,
        None,
        DailyWellness.from_api(daily_record(DAY, resting=60)),
        None,
        _history(57, days=2),
    )
    assert "resting_hr" in snap.missing


def test_hrv_without_status_uses_baseline() -> None:
    raw = hrv_record(DAY, status="NONE", avg=40)
    snap = build_snapshot("2026-11-20", None, HrvNight.from_api(raw), None, None, [])
    assert snap.signals[0].rating == "amber"


def test_overall_rules() -> None:
    from garmin_connector.recovery import Signal

    def sig(rating: str) -> Signal:
        return Signal(name="x", value=1, unit="u", rating=rating, note="")  # type: ignore[arg-type]

    assert overall_rating([sig("green"), sig("amber")]) == "green"
    assert overall_rating([sig("amber"), sig("amber")]) == "amber"
    assert overall_rating([sig("red"), sig("green")]) == "amber"
    assert overall_rating([sig("red"), sig("red")]) == "red"
