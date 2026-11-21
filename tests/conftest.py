"""Shared fixtures. All Garmin payloads here are synthetic, shaped like Garmin's
published Swagger examples; no real account data is used."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from datetime import date
from typing import Any

import httpx
import pytest
import respx

from garmin_connector import config
from garmin_connector.client import GarminClient
from garmin_connector.config import Settings
from garmin_connector.redact import REDACTOR
from garmin_connector.service import GarminService

FAKE_KEY = "fake-personal-api-key-0123456789"
FAKE_TOKEN = "fake-access-token-abcdefghijkl"
FAKE_ENV_KEY = "fake-env-api-key-0123456789"
FAKE_KEYRING_KEY = "fake-keyring-api-key-0123456789"
FAKE_PLAIN_TOKEN = "fake-plain-text-token-0123456789"
TOKEN_URL = config.BASE_URL + config.TOKEN_PATH


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=config.BASE_URL, assert_all_called=False) as mock:
        mock.post(config.TOKEN_PATH).respond(
            200, json={"access_token": FAKE_TOKEN, "expires_in": 86400}
        )
        yield mock


@pytest.fixture
async def client(router: respx.MockRouter) -> AsyncIterator[GarminClient]:
    http = httpx.AsyncClient(base_url=config.BASE_URL)
    garmin = GarminClient(Settings(), lambda: FAKE_KEY, http=http, sleep=_no_sleep)
    yield garmin
    await garmin.aclose()


@pytest.fixture
def service(client: GarminClient) -> GarminService:
    return GarminService(client)


@pytest.fixture(autouse=True)
def _register_fake_secrets() -> None:
    REDACTOR.register(FAKE_KEY)
    REDACTOR.register(FAKE_TOKEN)


def sleep_record(day: date, score: int | None = 82, seconds: int = 25200) -> dict[str, Any]:
    scores = {"overall": {"value": score, "qualifierKey": "GOOD"}} if score is not None else {}
    scores["remPercentage"] = {"value": 18, "qualifierKey": "FAIR"}
    return {
        "calendarDate": day.isoformat(),
        "sleepTimeSeconds": seconds,
        "deepSleepSeconds": 3840,
        "lightSleepSeconds": 14400,
        "remSleepSeconds": 6960,
        "awakeSleepSeconds": 540,
        "awakeCount": 2,
        "avgHeartRate": 54,
        "averageRespirationValue": 14.5,
        "averageSpO2Value": 96.0,
        "avgSleepStress": 18.0,
        "sleepScores": scores,
        "sleepNeed": {"actual": 480, "baseline": 470},
    }


def hrv_record(day: date, status: str = "BALANCED", avg: int = 48) -> dict[str, Any]:
    return {
        "calendarDate": day.isoformat(),
        "weeklyAvg": 50,
        "lastNightAvg": avg,
        "lastNight5MinHigh": 70,
        "baseline": {"lowUpper": 40, "balancedLow": 44, "balancedUpper": 58, "markerValue": 0.5},
        "status": status,
        "feedbackPhrase": "NONE",
    }


def daily_record(
    day: date, resting: int | None = 57, battery_high: int | None = 82, stress: int | None = 27
) -> dict[str, Any]:
    return {
        "calendarDate": day.isoformat(),
        "heartRate": {"minValue": 50, "maxValue": 150, "restingValue": resting},
        "stress": {
            "avgLevel": stress,
            "maxLevel": 90,
            "qualifier": "balanced",
            "restDurationInMillis": 27000000,
            "lowStressDurationInMillis": 12600000,
            "mediumStressDurationInMillis": 2220000,
            "highStressDurationInMillis": 300000,
        },
        "bodyBattery": {
            "minValue": 15,
            "maxValue": battery_high,
            "chargedValue": 60,
            "drainedValue": 55,
            "endOfDayValue": 20,
        },
        "respiration": {"avgValue": 15.0},
        "pulseOx": {"avgValue": 95.0},
        "intensityMinutes": {"moderate": 20, "vigorous": 5},
        "movement": json.dumps({"steps": {"goal": 8000, "value": 6786}}),
    }
