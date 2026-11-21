"""Date parsing, validation and chunking."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import MAX_TOOL_RANGE_DAYS


class DateRangeError(ValueError):
    """A date or date range from a tool call is invalid."""


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except (AttributeError, ValueError) as exc:
        raise DateRangeError(f"{field} must be a date like 2026-11-20, got {value!r}") from exc


def today(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


def validate_range(
    start: date, end: date, tz: ZoneInfo, max_days: int = MAX_TOOL_RANGE_DAYS
) -> None:
    if end < start:
        raise DateRangeError("end_date is before start_date")
    if (end - start).days + 1 > max_days:
        raise DateRangeError(f"Range is longer than {max_days} days; split it into smaller calls")
    if start > today(tz):
        raise DateRangeError("start_date is in the future")


def chunk_range(start: date, end: date, max_days: int) -> Iterator[tuple[date, date]]:
    """Split an inclusive date range into inclusive chunks of at most max_days."""
    if max_days < 1:
        raise ValueError("max_days must be at least 1")
    cursor = start
    step = timedelta(days=max_days - 1)
    while cursor <= end:
        chunk_end = min(cursor + step, end)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)
