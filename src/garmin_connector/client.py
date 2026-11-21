"""Read-only HTTP client for Garmin's Personal API.

Every method takes an inclusive date range, splits it into Garmin-sized chunks,
caches each chunk, and returns the raw JSON records for models.py to normalise.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

from . import config
from .auth import TokenManager
from .cache import TTLCache, ttl_for
from .dates import chunk_range, today
from .errors import GarminApiError, GarminAuthError

log = logging.getLogger(__name__)

_RETRY_STATUSES = frozenset({429, 502, 503, 504})
Record = dict[str, Any]


class GarminClient:
    def __init__(
        self,
        settings: config.Settings,
        api_key_loader: Callable[[], str],
        http: httpx.AsyncClient | None = None,
        cache: TTLCache | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._http = http or httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=config.HTTP_TIMEOUT_SECONDS,
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        self._tokens = TokenManager(self._http, api_key_loader)
        self._cache = cache or TTLCache()
        self._sleep = sleep

    @property
    def settings(self) -> config.Settings:
        return self._settings

    async def aclose(self) -> None:
        await self._http.aclose()

    # Public data methods -------------------------------------------------

    async def sleep_summaries(self, start: date, end: date) -> list[Record]:
        return await self._ranged(
            "sleep",
            start,
            end,
            config.SLEEP_CHUNK_DAYS,
            lambda s, e: (config.SLEEP_PATH, {"startDate": s, "endDate": e}),
            _as_list,
        )

    async def hrv_daily(self, start: date, end: date) -> list[Record]:
        return await self._ranged(
            "hrv",
            start,
            end,
            config.HRV_CHUNK_DAYS,
            lambda s, e: (config.HRV_PATH.format(start=s, end=e), None),
            lambda body: _as_list(body.get("hrvSummaries") if isinstance(body, dict) else None),
        )

    async def daily_summaries(self, start: date, end: date) -> list[Record]:
        return await self._ranged(
            "daily",
            start,
            end,
            config.DAILY_SUMMARIES_CHUNK_DAYS,
            lambda s, e: (config.DAILY_SUMMARIES_PATH, {"startDate": s, "endDate": e}),
            lambda body: _as_list(body.get("data") if isinstance(body, dict) else body),
        )

    async def vo2max_daily(self, start: date, end: date) -> list[Record]:
        return await self._ranged(
            "vo2max",
            start,
            end,
            config.VO2MAX_CHUNK_DAYS,
            lambda s, e: (config.VO2MAX_PATH.format(start=s, end=e), None),
            _as_list,
        )

    # Internals -----------------------------------------------------------

    async def _ranged(
        self,
        name: str,
        start: date,
        end: date,
        chunk_days: int,
        request_for: Callable[[str, str], tuple[str, dict[str, str] | None]],
        extract: Callable[[Any], list[Record]],
    ) -> list[Record]:
        records: list[Record] = []
        now = today(self._settings.timezone)
        for chunk_start, chunk_end in chunk_range(start, end, chunk_days):
            key = (name, chunk_start, chunk_end)
            cached = self._cache.get(key)
            if cached is None:
                path, params = request_for(chunk_start.isoformat(), chunk_end.isoformat())
                body = await self._get_json(path, params)
                cached = extract(body) if body is not None else []
                self._cache.set(key, cached, ttl_for(chunk_end, now))
            records.extend(cached)
        return records

    async def _get_json(self, path: str, params: dict[str, str] | None) -> Any:
        """GET a path with the bearer token. Returns None for 204 (no data)."""
        refreshed = False
        attempt = 0
        while True:
            token = await self._tokens.get_token()
            try:
                response = await self._http.get(
                    path, params=params, headers={"Authorization": f"Bearer {token}"}
                )
            except httpx.HTTPError as exc:
                if attempt < config.MAX_RETRIES:
                    attempt += 1
                    await self._sleep(_backoff(attempt, None))
                    continue
                log.warning("Network error calling %s: %s", path, type(exc).__name__)
                raise GarminApiError(0, path) from None

            status = response.status_code
            if status == 401 and not refreshed:
                # Token may have been revoked early; get a fresh one once.
                self._tokens.invalidate()
                refreshed = True
                continue
            if status == 401:
                raise GarminAuthError("Garmin refused the access token after a refresh")
            if status in _RETRY_STATUSES and attempt < config.MAX_RETRIES:
                attempt += 1
                wait = _backoff(attempt, response.headers.get("Retry-After"))
                log.info("Garmin returned %s for %s; retrying in %.1fs", status, path, wait)
                await self._sleep(wait)
                continue
            if status == 204:
                return None
            if status >= 400:
                raise GarminApiError(status, path)
            try:
                return response.json()
            except ValueError:
                raise GarminApiError(status, path) from None


def _backoff(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), config.MAX_RETRY_WAIT_SECONDS)
        except ValueError:
            pass
    return min(float(2**attempt), config.MAX_RETRY_WAIT_SECONDS)


def _as_list(body: Any) -> list[Record]:
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if isinstance(body, dict):
        return [body]
    return []
