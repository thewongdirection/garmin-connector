import logging

import httpx
import pytest
import respx

from garmin_connector import config
from garmin_connector.auth import TokenManager, parse_token_response
from garmin_connector.errors import GarminAuthError
from garmin_connector.redact import RedactingFilter, Redactor

from .conftest import FAKE_KEY, FAKE_TOKEN

NOW = 1_800_000_000.0


def _response(**kwargs: object) -> httpx.Response:
    return httpx.Response(200, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("body", "expected_expiry"),
    [
        ({"access_token": "tok-123456", "expires_in": 3600}, NOW + 3600),
        ({"accessToken": "tok-123456", "expiresAt": (NOW + 7200) * 1000}, NOW + 7200),
        ({"token": "tok-123456", "expiration": "2027-01-15T08:00:00Z"}, NOW),
        ({"access_token": "tok-123456"}, NOW + config.TOKEN_DEFAULT_LIFETIME_SECONDS),
    ],
)
def test_parse_token_response_json_shapes(body: dict[str, object], expected_expiry: float) -> None:
    token, expires_at = parse_token_response(_response(json=body), NOW)
    assert token == "tok-123456"
    assert expires_at == pytest.approx(expected_expiry)


def test_parse_token_response_plain_text() -> None:
    token, expires_at = parse_token_response(_response(text="tok-plain-123\n"), NOW)
    assert token == "tok-plain-123"
    assert expires_at == NOW + config.TOKEN_DEFAULT_LIFETIME_SECONDS


def test_parse_token_response_without_token_fails() -> None:
    with pytest.raises(GarminAuthError, match="did not contain"):
        parse_token_response(_response(json={"expires_in": 10}), NOW)


async def test_token_manager_caches_and_renews(router: respx.MockRouter) -> None:
    clock = [NOW]
    async with httpx.AsyncClient(base_url=config.BASE_URL) as http:
        manager = TokenManager(http, lambda: FAKE_KEY, clock=lambda: clock[0])
        assert await manager.get_token() == FAKE_TOKEN
        assert await manager.get_token() == FAKE_TOKEN
        assert router.routes[0].call_count == 1
        request = router.routes[0].calls.last.request
        assert request.headers["Authorization"] == f"ApiKey {FAKE_KEY}"

        clock[0] = NOW + 86400 - config.TOKEN_RENEW_MARGIN_SECONDS  # inside renew margin
        await manager.get_token()
        assert router.routes[0].call_count == 2


@pytest.mark.parametrize("status", [401, 403])
async def test_token_manager_rejected_key_message_has_no_secret(
    router: respx.MockRouter, status: int
) -> None:
    router.routes[0].respond(status, text=f"bad key {FAKE_KEY}")
    async with httpx.AsyncClient(base_url=config.BASE_URL) as http:
        manager = TokenManager(http, lambda: FAKE_KEY)
        with pytest.raises(GarminAuthError) as info:
            await manager.get_token()
    assert FAKE_KEY not in str(info.value)
    assert "set-key" in str(info.value)


async def test_token_manager_network_error(router: respx.MockRouter) -> None:
    router.routes[0].side_effect = httpx.ConnectError("boom")
    async with httpx.AsyncClient(base_url=config.BASE_URL) as http:
        with pytest.raises(GarminAuthError, match="Could not reach"):
            await TokenManager(http, lambda: FAKE_KEY).get_token()


def test_redactor_masks_registered_secrets_and_auth_headers() -> None:
    redactor = Redactor()
    redactor.register("supersecretvalue")
    redactor.register("abc")  # too short to register; avoids masking common text
    text = "key supersecretvalue; Authorization: Bearer xyz.123; ApiKey other-key abc"
    assert redactor.redact(text) == "key ***; Authorization: Bearer ***; ApiKey *** abc"


def test_logging_filter_redacts_message_args_and_exceptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.redact")
    caplog.handler.addFilter(RedactingFilter())
    try:
        with caplog.at_level(logging.INFO, logger="test.redact"):
            logger.info("token is %s", FAKE_TOKEN)
            try:
                raise RuntimeError(f"failed with {FAKE_KEY}")
            except RuntimeError:
                logger.exception("boom")
    finally:
        caplog.handler.filters.clear()
    assert FAKE_TOKEN not in caplog.text
    assert FAKE_KEY not in caplog.text
    assert "***" in caplog.text


@pytest.mark.parametrize(
    "body",
    ["<html><body>Sign in</body></html>", "short", "tok\nen-with-newline", "x" * 5000],
)
def test_parse_token_response_rejects_malformed_tokens(body: str) -> None:
    with pytest.raises(GarminAuthError, match="expected format"):
        parse_token_response(_response(text=body), NOW)


async def test_token_manager_rejects_redirects(router: respx.MockRouter) -> None:
    router.routes[0].respond(302, text="tok-looks-valid-123", headers={"Location": "/elsewhere"})
    async with httpx.AsyncClient(base_url=config.BASE_URL) as http:
        with pytest.raises(GarminAuthError, match="HTTP 302"):
            await TokenManager(http, lambda: FAKE_KEY).get_token()


async def test_token_manager_short_lived_token_is_not_refetched_every_call(
    router: respx.MockRouter,
) -> None:
    router.routes[0].respond(200, json={"access_token": FAKE_TOKEN, "expires_in": 600})
    clock = [NOW]
    async with httpx.AsyncClient(base_url=config.BASE_URL) as http:
        manager = TokenManager(http, lambda: FAKE_KEY, clock=lambda: clock[0])
        await manager.get_token()
        clock[0] = NOW + 200
        await manager.get_token()
        assert router.routes[0].call_count == 1
        clock[0] = NOW + 300  # halfway through a 10-minute token
        await manager.get_token()
        assert router.routes[0].call_count == 2
