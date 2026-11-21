from datetime import date

import httpx
import pytest
import respx

from garmin_connector import config
from garmin_connector.client import GarminClient
from garmin_connector.errors import GarminApiError, GarminAuthError

from .conftest import FAKE_TOKEN, daily_record, hrv_record, sleep_record

D1 = date(2026, 10, 1)


async def test_sleep_chunks_at_31_days_with_bearer(
    client: GarminClient, router: respx.MockRouter
) -> None:
    route = router.get(config.SLEEP_PATH).respond(200, json=[sleep_record(D1)])
    records = await client.sleep_summaries(D1, date(2026, 11, 9))
    assert len(records) == 2  # one record per chunk from the mock
    params = [dict(call.request.url.params) for call in route.calls]
    assert params == [
        {"startDate": "2026-10-01", "endDate": "2026-10-31"},
        {"startDate": "2026-11-01", "endDate": "2026-11-09"},
    ]
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {FAKE_TOKEN}"


async def test_hrv_and_daily_extract_wrapped_lists(
    client: GarminClient, router: respx.MockRouter
) -> None:
    router.get(config.HRV_PATH.format(start=D1, end=D1)).respond(
        200, json={"hrvSummaries": [hrv_record(D1)], "userProfilePk": 1}
    )
    router.get(config.DAILY_SUMMARIES_PATH).respond(200, json={"data": [daily_record(D1)]})
    assert (await client.hrv_daily(D1, D1))[0]["lastNightAvg"] == 48
    assert (await client.daily_summaries(D1, D1))[0]["calendarDate"] == "2026-10-01"


async def test_responses_are_cached(client: GarminClient, router: respx.MockRouter) -> None:
    route = router.get(config.SLEEP_PATH).respond(200, json=[sleep_record(D1)])
    await client.sleep_summaries(D1, D1)
    await client.sleep_summaries(D1, D1)
    assert route.call_count == 1


async def test_204_means_no_data(client: GarminClient, router: respx.MockRouter) -> None:
    router.get(config.HRV_PATH.format(start=D1, end=D1)).respond(204)
    assert await client.hrv_daily(D1, D1) == []


async def test_401_refreshes_token_once(client: GarminClient, router: respx.MockRouter) -> None:
    route = router.get(config.SLEEP_PATH)
    route.side_effect = [httpx.Response(401), httpx.Response(200, json=[sleep_record(D1)])]
    assert len(await client.sleep_summaries(D1, D1)) == 1
    assert router.routes[0].call_count == 2  # token fetched twice


async def test_repeated_401_is_auth_error(client: GarminClient, router: respx.MockRouter) -> None:
    router.get(config.SLEEP_PATH).respond(401)
    with pytest.raises(GarminAuthError):
        await client.sleep_summaries(D1, D1)


async def test_429_is_retried_then_succeeds(client: GarminClient, router: respx.MockRouter) -> None:
    route = router.get(config.SLEEP_PATH)
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(503),
        httpx.Response(200, json=[sleep_record(D1)]),
    ]
    assert len(await client.sleep_summaries(D1, D1)) == 1
    assert route.call_count == 3


async def test_retries_are_bounded(client: GarminClient, router: respx.MockRouter) -> None:
    route = router.get(config.SLEEP_PATH).respond(503)
    with pytest.raises(GarminApiError) as info:
        await client.sleep_summaries(D1, D1)
    assert info.value.status == 503
    assert route.call_count == config.MAX_RETRIES + 1


async def test_client_error_is_not_retried(client: GarminClient, router: respx.MockRouter) -> None:
    route = router.get(config.SLEEP_PATH).respond(400)
    with pytest.raises(GarminApiError, match="HTTP 400"):
        await client.sleep_summaries(D1, D1)
    assert route.call_count == 1


async def test_network_error_is_retried_then_reported(
    client: GarminClient, router: respx.MockRouter
) -> None:
    route = router.get(config.SLEEP_PATH)
    route.side_effect = httpx.ConnectError("down")
    with pytest.raises(GarminApiError) as info:
        await client.sleep_summaries(D1, D1)
    assert info.value.status == 0
    assert route.call_count == config.MAX_RETRIES + 1


async def test_non_json_body_is_api_error(client: GarminClient, router: respx.MockRouter) -> None:
    router.get(config.SLEEP_PATH).respond(200, text="<html>")
    with pytest.raises(GarminApiError):
        await client.sleep_summaries(D1, D1)
