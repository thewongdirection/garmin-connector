from datetime import date
from typing import Any

import keyring
import pytest
import respx
from keyring.errors import KeyringError

from garmin_connector import cli, config, credentials

from .conftest import FAKE_KEY, sleep_record


class MemoryKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, user: str) -> str | None:
        return self.store.get((service, user))

    def set_password(self, service: str, user: str, value: str) -> None:
        self.store[(service, user)] = value

    def delete_password(self, service: str, user: str) -> None:
        if (service, user) not in self.store:
            raise keyring.errors.PasswordDeleteError("missing")
        del self.store[(service, user)]


@pytest.fixture
def memory_keyring(monkeypatch: pytest.MonkeyPatch) -> MemoryKeyring:
    fake = MemoryKeyring()
    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, name, getattr(fake, name))
    monkeypatch.delenv(config.ENV_API_KEY, raising=False)
    return fake


def test_env_var_wins_over_keyring(
    memory_keyring: MemoryKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials.store_api_key("from-keyring-123")
    monkeypatch.setenv(config.ENV_API_KEY, "  from-env-12345 ")
    assert credentials.load_api_key() == "from-env-12345"


def test_keyring_roundtrip_and_delete(memory_keyring: MemoryKeyring) -> None:
    credentials.store_api_key(" stored-key-123 ")
    assert credentials.load_api_key() == "stored-key-123"
    assert credentials.delete_api_key() is True
    assert credentials.delete_api_key() is False
    with pytest.raises(credentials.MissingApiKeyError):
        credentials.load_api_key()


def test_store_rejects_empty(memory_keyring: MemoryKeyring) -> None:
    with pytest.raises(ValueError):
        credentials.store_api_key("   ")


def test_keyring_failure_is_treated_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: Any) -> None:
        raise KeyringError("no backend")

    monkeypatch.setattr(keyring, "get_password", broken)
    monkeypatch.delenv(config.ENV_API_KEY, raising=False)
    with pytest.raises(credentials.MissingApiKeyError):
        credentials.load_api_key()


def test_cli_set_key_stores_without_echo(
    memory_keyring: MemoryKeyring,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("getpass.getpass", lambda _prompt: FAKE_KEY)
    assert cli.main(["set-key"]) == 0
    assert memory_keyring.get_password(config.KEYRING_SERVICE, config.KEYRING_USERNAME) == FAKE_KEY
    out = capsys.readouterr()
    assert FAKE_KEY not in out.out + out.err


def test_cli_set_key_empty(memory_keyring: MemoryKeyring, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "  ")
    assert cli.main(["set-key"]) == 1
    assert memory_keyring.store == {}


def test_cli_serve_without_key_exits_cleanly(
    memory_keyring: MemoryKeyring, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["serve"]) == 2
    assert "set-key" in capsys.readouterr().err


def test_cli_check_reports_each_endpoint(
    router: respx.MockRouter,
    memory_keyring: MemoryKeyring,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(config.ENV_API_KEY, FAKE_KEY)
    router.get(config.SLEEP_PATH).respond(200, json=[sleep_record(date(2026, 11, 1))])
    router.get(path__regex=r"^/hrv-service/").respond(204)
    router.get(config.DAILY_SUMMARIES_PATH).respond(200, json={"data": []})
    router.get(path__regex=r"^/metrics-service/").respond(500)
    assert cli.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "OK    sleep: 1 record(s)" in out
    assert "OK    hrv: 0 record(s)" in out
    assert "OK    daily wellness: 0 record(s)" in out
    assert "FAIL  vo2 max: Garmin returned HTTP 500" in out
    assert FAKE_KEY not in out


def test_bad_timezone_gives_clear_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(config.ENV_TIMEZONE, "Mars/Olympus_Mons")
    monkeypatch.setenv(config.ENV_API_KEY, FAKE_KEY)
    assert cli.main(["check"]) == 2
    assert "not a known time zone" in capsys.readouterr().err


def test_blank_timezone_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(config.ENV_TIMEZONE, "  ")
    assert str(config.Settings.from_env().timezone) == config.DEFAULT_TIMEZONE
