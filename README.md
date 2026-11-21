# garmin-connector

Connector to allow Claude to read anything it doesn't already see via other connectors like Strava etc.

A small, read-only MCP server that lets Claude read **your own** Garmin health data through
Garmin's official [Personal API](https://developer.garmin.com/gc-developer-program/personal/personal-api/):
sleep, HRV, Body Battery, stress, resting heart rate and VO2 max. Workouts are left to Strava.

It never writes to Garmin, never stores your key in a file, and never logs the key or token.

## Tools

| Tool | What it returns |
| --- | --- |
| `get_sleep(start_date, end_date)` | Sleep score and sub-scores, minutes in each stage, sleeping HR, respiration, SpO2 |
| `get_hrv(start_date, end_date)` | Last-night average, 5-min high, weekly average, baseline range, Garmin HRV status |
| `get_daily_wellness(start_date, end_date)` | Resting/min/max HR, stress, Body Battery, respiration, SpO2, intensity minutes, steps |
| `get_vo2max(start_date, end_date)` | VO2 max estimates by day and sport |
| `get_recovery_snapshot(date?)` | Green/amber/red check from sleep, HRV, Body Battery, resting HR and yesterday's stress |

Dates are `YYYY-MM-DD` in your local time zone (default `Asia/Singapore`, override with
`GARMIN_TZ`). Ranges are inclusive, up to 90 days per call; the client splits them into
Garmin-sized requests and caches results in memory.

The recovery snapshot is this tool's own estimate. Garmin's Training Readiness, Training
Status, recovery time and endurance score are not available through the Personal API.

## Setup on Windows

1. **Create a Garmin Personal API key** (only you can do this): sign in to Garmin Connect on
   the web, open Settings, then Personal API, choose **Create Key**, read and accept Garmin's
   terms, pick an expiry (1 year is easiest), and copy the key. It is shown only once.
2. **Install** (Python 3.11 or newer):

   ```powershell
   cd garmin-connector
   py -m venv .venv
   .venv\Scripts\pip install -e .
   ```

3. **Store the key** in Windows Credential Manager (input is hidden):

   ```powershell
   .venv\Scripts\garmin-connector set-key
   ```

4. **Check it works.** This prints a record count per endpoint for the last 7 days, never data
   or secrets:

   ```powershell
   .venv\Scripts\garmin-connector check
   ```

5. **Add it to Claude Code** (use the full path to your checkout):

   ```powershell
   claude mcp add garmin --scope user -- C:\path\to\garmin-connector\.venv\Scripts\garmin-connector.exe serve
   ```

When the key nears expiry Garmin emails you; create a new one and run `set-key` again.
`garmin-connector delete-key` removes the stored key.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
mypy src
```

Tests use synthetic responses shaped like Garmin's published Swagger examples and never call
Garmin. CI runs lint, types, tests and a secret scan on every push.

## Layout

```
src/garmin_connector/
  config.py       endpoint paths, range limits, settings
  credentials.py  key from env var or OS credential store
  auth.py         key -> 24h access token, cached in memory
  client.py       HTTP, chunking, retries, caching
  models.py       normalised, unit-labelled records
  recovery.py     green/amber/red snapshot
  service.py      tool logic (transport-independent)
  server.py       MCP tool registration
  cli.py          serve / set-key / delete-key / check
```

`service.py` and `server.py` don't depend on stdio, so the same code can later run as a hosted
HTTPS server (for example on Google Cloud Run) behind sign-in.

## Notes

- Personal use of your own account only, per Garmin's terms.
- Garmin doesn't publish rate limits. The client retries 429 and transient 5xx responses at
  most twice with backoff, and caches settled days for 24 hours.
- The token endpoint's response format and the data-call header aren't spelled out in
  Garmin's docs; `garmin-connector check` confirms both on first use.
