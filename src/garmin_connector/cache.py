"""Small in-memory TTL cache for Garmin responses."""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from datetime import date, timedelta
from typing import Any

from .config import CACHE_TTL_RECENT_SECONDS, CACHE_TTL_SETTLED_SECONDS, SETTLED_AFTER_DAYS


def ttl_for(end: date, today: date) -> float:
    """Data for older days rarely changes; recent days can still sync late."""
    if end <= today - timedelta(days=SETTLED_AFTER_DAYS):
        return CACHE_TTL_SETTLED_SECONDS
    return CACHE_TTL_RECENT_SECONDS


class TTLCache:
    def __init__(self, clock: Callable[[], float] = time.monotonic, max_entries: int = 512) -> None:
        self._clock = clock
        self._max_entries = max_entries
        self._entries: dict[Hashable, tuple[float, Any]] = {}

    def get(self, key: Hashable) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._entries[key]
            return None
        return value

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        if len(self._entries) >= self._max_entries:
            self._evict()
        self._entries[key] = (self._clock() + ttl, value)

    def clear(self) -> None:
        self._entries.clear()

    def _evict(self) -> None:
        now = self._clock()
        for key in [k for k, (exp, _) in self._entries.items() if exp <= now]:
            del self._entries[key]
        while len(self._entries) >= self._max_entries:
            oldest = min(self._entries, key=lambda k: self._entries[k][0])
            del self._entries[oldest]
