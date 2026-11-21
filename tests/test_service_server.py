import json
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult

from garmin_connector import config
from garmin_connector.dates import DateRangeError, today
from garmin_connector.server import build_server
from garmin_connector.service import GarminService

from .conftest import FAKE_KEY, FAKE_TOKEN, daily_record, hrv_record, sleep_record

SGT = ZoneInfo("Asia/Singapore")


async def test_recovery_snapshot_end_to_end(
    service: GarminService, router: respx.MockRouter
) -> None:
    day = today(SGT) - timedelta(days=1)
    router.get(config.SLEEP_PATH).respond(200, json=[sleep_record(day, score=81)])
    router.get(config.HRV_PATH.format(start=day, end=day)).respond(
        200, json={"hrvSummaries": [hrv_record(day)]}
    )
    history = [daily_record(day - timedelta(days=i), resting=57) for i in range(1, 8)]
    daily = router.get(config.DAILY_SUMMARIES_PATH).respond(
        200, json={"data": [daily_record(day, resting=58), *history]}
    )
    snap = await service.recovery_snapshot(day.isoformat())
    assert snap.date == day.isoformat()
    assert snap.overall == "green"
    assert snap.missing == []
    assert dict(daily.calls.last.request.url.params) == {
        "startDate": (day - timedelta(days=7)).isoformat(),
        "endDate": day.isoformat(),
    }


async def test_service_sorts_and_validates(
    service: GarminService, router: respx.MockRouter
) -> None:
    d2 = today(SGT) - timedelta(days=1)
    d1 = d2 - timedelta(days=1)
    router.get(config.SLEEP_PATH).respond(200, json=[sleep_record(d2), sleep_record(d1)])
    nights = await service.sleep(d1.isoformat(), d2.isoformat())
    assert [n.date for n in nights] == [d1.isoformat(), d2.isoformat()]
    with pytest.raises(DateRangeError):
        await service.sleep(d2.isoformat(), d1.isoformat())


async def test_server_lists_read_only_tools(service: GarminService) -> None:
    tools = await build_server(service).list_tools()
    assert {t.name for t in tools} == {
        "get_sleep",
        "get_hrv",
        "get_daily_wellness",
        "get_vo2max",
        "get_recovery_snapshot",
    }
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


async def test_server_tool_returns_data(service: GarminService, router: respx.MockRouter) -> None:
    day = today(SGT) - timedelta(days=1)
    router.get(config.DAILY_SUMMARIES_PATH).respond(200, json={"data": [daily_record(day)]})
    result = await build_server(service).call_tool(
        "get_daily_wellness", {"start_date": day.isoformat(), "end_date": day.isoformat()}
    )
    assert isinstance(result, CallToolResult)
    assert not result.is_error
    texts = [getattr(c, "text", "") for c in result.content]
    assert [json.loads(t)["resting_hr_bpm"] for t in texts] == [57]


async def test_server_bad_dates_give_readable_error(service: GarminService) -> None:
    with pytest.raises(ToolError, match="start_date must be a date"):
        await build_server(service).call_tool(
            "get_sleep", {"start_date": "last week", "end_date": "2026-11-20"}
        )


async def test_server_garmin_errors_never_leak_secrets(
    service: GarminService, router: respx.MockRouter
) -> None:
    router.routes[0].respond(401, text=f"rejected {FAKE_KEY}")
    day = (today(SGT) - timedelta(days=1)).isoformat()
    with pytest.raises(ToolError) as info:
        await build_server(service).call_tool("get_hrv", {"start_date": day, "end_date": day})
    message = str(info.value)
    assert "rejected the Personal API key" in message
    assert FAKE_KEY not in message
    assert FAKE_TOKEN not in message


async def test_recovery_snapshot_survives_one_failing_endpoint(
    service: GarminService, router: respx.MockRouter
) -> None:
    day = today(SGT) - timedelta(days=1)
    router.get(config.SLEEP_PATH).respond(200, json=[sleep_record(day, score=81)])
    router.get(config.HRV_PATH.format(start=day, end=day)).respond(500)
    router.get(config.DAILY_SUMMARIES_PATH).respond(200, json={"data": [daily_record(day)]})
    snap = await service.recovery_snapshot(day.isoformat())
    assert "hrv" in snap.missing
    assert "sleep_score" not in snap.missing


async def test_service_does_not_ask_garmin_for_future_days(
    service: GarminService, router: respx.MockRouter
) -> None:
    now = today(SGT)
    route = router.get(config.SLEEP_PATH).respond(200, json=[])
    await service.sleep(now.isoformat(), (now + timedelta(days=5)).isoformat())
    assert route.calls.last.request.url.params["endDate"] == now.isoformat()
