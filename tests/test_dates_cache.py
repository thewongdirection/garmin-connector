from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest

from garmin_connector.cache import TTLCache, ttl_for
from garmin_connector.config import CACHE_TTL_RECENT_SECONDS, CACHE_TTL_SETTLED_SECONDS
from garmin_connector.dates import DateRangeError, chunk_range, parse_date, today, validate_range

SGT = ZoneInfo("Asia/Singapore")


def test_chunk_range_splits_inclusive_ranges() -> None:
    chunks = list(chunk_range(date(2026, 10, 1), date(2026, 11, 9), 31))
    assert chunks == [
        (date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 11, 1), date(2026, 11, 9)),
    ]


def test_chunk_range_single_day() -> None:
    day = date(2026, 11, 20)
    assert list(chunk_range(day, day, 28)) == [(day, day)]


def test_chunk_range_exact_multiple() -> None:
    chunks = list(chunk_range(date(2026, 1, 1), date(2026, 2, 25), 28))
    assert len(chunks) == 2
    assert all((end - start).days + 1 == 28 for start, end in chunks)


def test_chunk_range_rejects_zero() -> None:
    with pytest.raises(ValueError):
        list(chunk_range(date(2026, 1, 1), date(2026, 1, 2), 0))


@pytest.mark.parametrize("bad", ["", "20-11-2026", "2026-13-01", "yesterday"])
def test_parse_date_rejects_bad_input(bad: str) -> None:
    with pytest.raises(DateRangeError, match="start_date"):
        parse_date(bad, "start_date")


def test_validate_range_rules() -> None:
    now = today(SGT)
    validate_range(now - timedelta(days=89), now, SGT)
    with pytest.raises(DateRangeError, match="before"):
        validate_range(now, now - timedelta(days=1), SGT)
    with pytest.raises(DateRangeError, match="90 days"):
        validate_range(now - timedelta(days=90), now, SGT)
    with pytest.raises(DateRangeError, match="future"):
        validate_range(now + timedelta(days=1), now + timedelta(days=2), SGT)


def test_ttl_for_settled_and_recent() -> None:
    now = date(2026, 11, 21)
    assert ttl_for(date(2026, 11, 19), now) == CACHE_TTL_SETTLED_SECONDS
    assert ttl_for(date(2026, 11, 20), now) == CACHE_TTL_RECENT_SECONDS
    assert ttl_for(now, now) == CACHE_TTL_RECENT_SECONDS


def test_ttl_cache_expires_and_evicts() -> None:
    clock = [0.0]
    cache = TTLCache(clock=lambda: clock[0], max_entries=2)
    cache.set("a", 1, ttl=10)
    assert cache.get("a") == 1
    clock[0] = 10
    assert cache.get("a") is None
    cache.set("b", 2, ttl=100)
    cache.set("c", 3, ttl=50)
    cache.set("d", 4, ttl=100)  # evicts the soonest-expiring entry ("c")
    assert cache.get("c") is None
    assert cache.get("b") == 2
    assert cache.get("d") == 4
