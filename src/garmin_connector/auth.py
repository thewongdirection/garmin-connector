"""Swap the Personal API key for a short-lived access token and keep it fresh.

Garmin documents the token endpoint (POST with "Authorization: ApiKey <key>") and
a 24-hour token lifetime, but not the exact response body. The parser below
accepts the common shapes and falls back to the documented lifetime.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from .config import TOKEN_DEFAULT_LIFETIME_SECONDS, TOKEN_PATH, TOKEN_RENEW_MARGIN_SECONDS
from .errors import GarminAuthError
from .redact import REDACTOR

_TOKEN_KEYS = ("access_token", "accessToken", "token")
_EXPIRES_IN_KEYS = ("expires_in", "expiresIn")
_EXPIRES_AT_KEYS = ("expires_at", "expiresAt", "expiration", "expirationTime")
# A bearer token is one run of printable, non-space ASCII. Anything else (an HTML
# error page, a multi-line body) is rejected rather than sent back as a header.
_TOKEN_SHAPE = re.compile(r"[\x21-\x7e]{8,4096}")


def parse_token_response(response: httpx.Response, now: float) -> tuple[str, float]:
    """Return (token, expires_at_epoch_seconds) from a token response."""
    payload: Any
    try:
        payload = response.json()
    except ValueError:
        payload = response.text.strip()

    if isinstance(payload, str):
        token = payload.strip().strip('"')
        expires_at = now + TOKEN_DEFAULT_LIFETIME_SECONDS
    elif isinstance(payload, dict):
        token = next((str(payload[k]) for k in _TOKEN_KEYS if payload.get(k)), "")
        expires_at = _expiry_from(payload, now)
    else:
        token = ""
        expires_at = now

    if not token:
        raise GarminAuthError("Garmin's token response did not contain an access token")
    if not _TOKEN_SHAPE.fullmatch(token):
        raise GarminAuthError("Garmin's token response was not in the expected format")
    return token, expires_at


def _expiry_from(payload: dict[str, Any], now: float) -> float:
    for key in _EXPIRES_IN_KEYS:
        value = payload.get(key)
        if isinstance(value, int | float) and value > 0:
            return now + float(value)
    for key in _EXPIRES_AT_KEYS:
        value = payload.get(key)
        if isinstance(value, int | float) and value > 0:
            # Epoch milliseconds or seconds.
            return float(value) / 1000 if value > 1e11 else float(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return now + TOKEN_DEFAULT_LIFETIME_SECONDS


class TokenManager:
    """Fetches and caches the access token in memory only."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key_loader: Callable[[], str],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._http = http
        self._load_key = api_key_loader
        self._clock = clock
        self._token: str | None = None
        self._renew_at = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        async with self._lock:
            if self._token and self._clock() < self._renew_at:
                return self._token
            now = self._clock()
            token, expires_at = await self._fetch(now)
            # Renew an hour early, or halfway through a token that lives under two hours.
            margin = min(TOKEN_RENEW_MARGIN_SECONDS, max(expires_at - now, 0.0) / 2)
            self._token, self._renew_at = token, expires_at - margin
            return token

    def invalidate(self) -> None:
        self._token = None
        self._renew_at = 0.0

    async def _fetch(self, now: float) -> tuple[str, float]:
        key = self._load_key()
        try:
            response = await self._http.post(TOKEN_PATH, headers={"Authorization": f"ApiKey {key}"})
        except httpx.HTTPError as exc:
            raise GarminAuthError(
                f"Could not reach Garmin's token service ({type(exc).__name__})"
            ) from None
        if response.status_code in (401, 403):
            raise GarminAuthError(
                "Garmin rejected the Personal API key. It may have expired or been deleted; "
                "create a new one in Garmin Connect and run 'garmin-connector set-key'."
            )
        if not response.is_success:
            raise GarminAuthError(f"Garmin's token service returned HTTP {response.status_code}")
        token, expires_at = parse_token_response(response, now)
        REDACTOR.register(token)
        return token, expires_at
