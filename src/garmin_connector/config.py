"""Constants and runtime settings.

Endpoint paths and per-call range limits come from Garmin's Personal API Swagger
documentation (Garmin Connect Personal API 1.0.0). Where Garmin does not state a
limit, a conservative value is used and marked as such.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_URL = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"  # noqa: S105 (URL path, not a secret)

SLEEP_PATH = "/sleep-service/sleep/dailySleepSummariesByDate"
HRV_PATH = "/hrv-service/hrv/daily/{start}/{end}"
DAILY_SUMMARIES_PATH = "/usersummary-service/v2/dailysummaries"
VO2MAX_PATH = "/metrics-service/metrics/maxmet/daily/{start}/{end}"

# Maximum days per Garmin request.
SLEEP_CHUNK_DAYS = 31  # stated by Garmin
DAILY_SUMMARIES_CHUNK_DAYS = 365  # stated by Garmin ("up to a maximum of 1 year")
HRV_CHUNK_DAYS = 28  # not stated by Garmin; conservative
VO2MAX_CHUNK_DAYS = 28  # not stated by Garmin; conservative

# Largest range a single tool call may ask for, to keep responses small.
MAX_TOOL_RANGE_DAYS = 90

KEYRING_SERVICE = "garmin-connector"
KEYRING_USERNAME = "garmin-personal-api-key"
ENV_API_KEY = "GARMIN_PERSONAL_API_KEY"
ENV_TIMEZONE = "GARMIN_TZ"
DEFAULT_TIMEZONE = "Asia/Singapore"

HTTP_TIMEOUT_SECONDS = 20.0
MAX_RETRIES = 2  # extra attempts on 429 and transient 5xx
MAX_RETRY_WAIT_SECONDS = 10.0

TOKEN_DEFAULT_LIFETIME_SECONDS = 24 * 3600
TOKEN_RENEW_MARGIN_SECONDS = 3600

CACHE_TTL_SETTLED_SECONDS = 24 * 3600
CACHE_TTL_RECENT_SECONDS = 15 * 60
SETTLED_AFTER_DAYS = 2


class ConfigError(ValueError):
    """A setting from the environment is invalid."""


@dataclass(frozen=True)
class Settings:
    """Runtime settings, read from the environment."""

    base_url: str = BASE_URL
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo(DEFAULT_TIMEZONE))

    @classmethod
    def from_env(cls) -> Settings:
        tz_name = os.environ.get(ENV_TIMEZONE, "").strip() or DEFAULT_TIMEZONE
        try:
            timezone = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ConfigError(
                f"{ENV_TIMEZONE}={tz_name!r} is not a known time zone, e.g. Asia/Singapore"
            ) from None
        return cls(timezone=timezone)
