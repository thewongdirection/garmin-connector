"""MCP server: registers read-only tools over a GarminService."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .config import MAX_TOOL_RANGE_DAYS
from .credentials import MissingApiKeyError
from .dates import DateRangeError
from .errors import GarminError
from .service import GarminService

_T = TypeVar("_T")

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)

INSTRUCTIONS = f"""\
Read-only access to the user's own Garmin health data via Garmin's Personal API.
Dates are YYYY-MM-DD in the user's local time zone; ranges are inclusive and at most
{MAX_TOOL_RANGE_DAYS} days per call. A sleep record's date is the morning the user woke up.
Workouts are not covered here (use Strava). Garmin's Training Readiness, Training Status,
recovery time and endurance score are not available through this API. Missing values are
null, not zero: the watch may not have been worn or synced.
"""


def _dump(items: list[Any]) -> list[dict[str, Any]]:
    return [item.model_dump() for item in items]


async def _expected(call: Awaitable[_T]) -> _T:
    """Turn anticipated failures into ToolError so the model sees a useful message.

    These messages never contain the API key or token (see errors.py).
    """
    try:
        return await call
    except (DateRangeError, GarminError, MissingApiKeyError) as exc:
        raise ToolError(str(exc)) from None


def build_server(service: GarminService) -> MCPServer:
    mcp: MCPServer = MCPServer(
        name="garmin-connector", version=__version__, instructions=INSTRUCTIONS
    )

    @mcp.tool(annotations=READ_ONLY)
    async def get_sleep(start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Nightly sleep: Garmin sleep score and sub-scores, minutes in deep, light, REM
        and awake, average sleeping heart rate, respiration, SpO2 and sleep stress."""
        return _dump(await _expected(service.sleep(start_date, end_date)))

    @mcp.tool(annotations=READ_ONLY)
    async def get_hrv(start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Nightly HRV in milliseconds: last-night average, 5-minute high, 7-day average,
        balanced baseline range and Garmin's HRV status."""
        return _dump(await _expected(service.hrv(start_date, end_date)))

    @mcp.tool(annotations=READ_ONLY)
    async def get_daily_wellness(start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Per-day resting/min/max heart rate, stress (average, max, minutes by level),
        Body Battery (high, low, charged, drained, end of day), respiration, SpO2,
        intensity minutes and steps."""
        return _dump(await _expected(service.daily_wellness(start_date, end_date)))

    @mcp.tool(annotations=READ_ONLY)
    async def get_vo2max(start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Garmin VO2 max estimates by day and sport (generic = running/walking, cycling)."""
        return _dump(await _expected(service.vo2max(start_date, end_date)))

    @mcp.tool(annotations=READ_ONLY)
    async def get_recovery_snapshot(date: str | None = None) -> dict[str, Any]:
        """One-call morning check for a date (default today): sleep score, HRV vs status,
        Body Battery, resting heart rate vs the previous 7 days, and yesterday's stress,
        each rated green/amber/red plus an overall rating. This is the connector's own
        estimate, not Garmin's Training Readiness."""
        return (await _expected(service.recovery_snapshot(date))).model_dump()

    return mcp
