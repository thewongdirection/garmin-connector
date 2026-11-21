"""Tool logic, independent of the MCP transport so it can be hosted later unchanged."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from datetime import date, timedelta
from typing import TypeVar

from .client import GarminClient, Record
from .dates import parse_date, today, validate_range
from .errors import GarminApiError
from .models import DailyWellness, HrvNight, SleepNight, Vo2MaxReading
from .recovery import RecoverySnapshot, build_snapshot

log = logging.getLogger(__name__)

RHR_HISTORY_DAYS = 7


class GarminService:
    def __init__(self, client: GarminClient) -> None:
        self._client = client
        self._tz = client.settings.timezone

    def _range(self, start_date: str, end_date: str) -> tuple[date, date]:
        start = parse_date(start_date, "start_date")
        end = parse_date(end_date, "end_date")
        validate_range(start, end, self._tz)
        # Garmin has nothing after today; don't ask it for future days.
        return start, min(end, today(self._tz))

    async def sleep(self, start_date: str, end_date: str) -> list[SleepNight]:
        start, end = self._range(start_date, end_date)
        raw = await self._client.sleep_summaries(start, end)
        return _sorted([SleepNight.from_api(r) for r in raw])

    async def hrv(self, start_date: str, end_date: str) -> list[HrvNight]:
        start, end = self._range(start_date, end_date)
        raw = await self._client.hrv_daily(start, end)
        return _sorted([HrvNight.from_api(r) for r in raw])

    async def daily_wellness(self, start_date: str, end_date: str) -> list[DailyWellness]:
        start, end = self._range(start_date, end_date)
        raw = await self._client.daily_summaries(start, end)
        return _sorted([DailyWellness.from_api(r) for r in raw])

    async def vo2max(self, start_date: str, end_date: str) -> list[Vo2MaxReading]:
        start, end = self._range(start_date, end_date)
        raw = await self._client.vo2max_daily(start, end)
        readings = [reading for r in raw for reading in Vo2MaxReading.from_api(r)]
        return sorted(readings, key=lambda r: (r.date, r.sport))

    async def recovery_snapshot(self, day: str | None = None) -> RecoverySnapshot:
        target = parse_date(day, "date") if day else today(self._tz)
        validate_range(target, target, self._tz)
        history_start = target - timedelta(days=RHR_HISTORY_DAYS)

        # One failing endpoint should leave a gap in the snapshot, not sink it.
        # Auth and other errors still propagate.
        sleep_raw, hrv_raw, daily_raw = await asyncio.gather(
            _or_empty("sleep", self._client.sleep_summaries(target, target)),
            _or_empty("hrv", self._client.hrv_daily(target, target)),
            _or_empty("daily", self._client.daily_summaries(history_start, target)),
        )
        iso = target.isoformat()
        yesterday = (target - timedelta(days=1)).isoformat()
        nights = {n.date: n for n in (SleepNight.from_api(r) for r in sleep_raw)}
        hrvs = {h.date: h for h in (HrvNight.from_api(r) for r in hrv_raw)}
        days = {d.date: d for d in (DailyWellness.from_api(r) for r in daily_raw)}
        history = [d for key, d in sorted(days.items()) if key < iso]

        return build_snapshot(
            day=iso,
            night=nights.get(iso),
            hrv=hrvs.get(iso),
            today_wellness=days.get(iso),
            yesterday_wellness=days.get(yesterday),
            rhr_history=history,
        )


async def _or_empty(name: str, call: Awaitable[list[Record]]) -> list[Record]:
    try:
        return await call
    except GarminApiError as exc:
        log.warning("Recovery snapshot: %s unavailable (%s)", name, exc)
        return []


_Dated = TypeVar("_Dated", SleepNight, HrvNight, DailyWellness)


def _sorted(items: list[_Dated]) -> list[_Dated]:
    return sorted(items, key=lambda item: item.date)
