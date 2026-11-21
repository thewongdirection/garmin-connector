"""Command line: run the server, store the key, or check access.

garmin-connector serve        run the MCP server over stdio (what Claude Code starts)
garmin-connector set-key      store your Garmin Personal API key in the OS credential store
garmin-connector delete-key   remove it again
garmin-connector check        confirm the key works and each endpoint answers (no data shown)
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from datetime import timedelta

from . import credentials
from .client import GarminClient
from .config import ConfigError, Settings
from .dates import today
from .errors import GarminError
from .redact import RedactingFilter
from .server import build_server
from .service import GarminService


def _configure_logging(verbose: bool) -> None:
    # stdout carries the MCP protocol, so logs go to stderr only.
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    # httpx logs full request URLs at INFO; keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _make_client() -> GarminClient:
    return GarminClient(Settings.from_env(), credentials.load_api_key)


def _serve() -> int:
    credentials.load_api_key()  # fail fast with a clear message
    client = _make_client()
    build_server(GarminService(client)).run("stdio")
    return 0


def _set_key() -> int:
    key = getpass.getpass("Paste your Garmin Personal API key (input hidden): ")
    if not key.strip():
        print("No key entered; nothing stored.", file=sys.stderr)
        return 1
    credentials.store_api_key(key)
    print("Key stored in your OS credential store.", file=sys.stderr)
    return 0


def _delete_key() -> int:
    removed = credentials.delete_api_key()
    print("Key removed." if removed else "No stored key found.", file=sys.stderr)
    return 0


async def _check() -> int:
    client = _make_client()
    yesterday = today(client.settings.timezone) - timedelta(days=1)
    week_ago = yesterday - timedelta(days=6)
    checks = {
        "sleep": client.sleep_summaries,
        "hrv": client.hrv_daily,
        "daily wellness": client.daily_summaries,
        "vo2 max": client.vo2max_daily,
    }
    failures = 0
    try:
        for name, fetch in checks.items():
            try:
                records = await fetch(week_ago, yesterday)
                print(f"OK    {name}: {len(records)} record(s) for the last 7 days")
            except GarminError as exc:
                failures += 1
                print(f"FAIL  {name}: {exc}")
    finally:
        await client.aclose()
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="garmin-connector",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command", nargs="?", default="serve", choices=["serve", "set-key", "delete-key", "check"]
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    try:
        if args.command == "set-key":
            return _set_key()
        if args.command == "delete-key":
            return _delete_key()
        if args.command == "check":
            return asyncio.run(_check())
        return _serve()
    except (credentials.MissingApiKeyError, ConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
