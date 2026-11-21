"""Where the Garmin Personal API key lives.

Order: the GARMIN_PERSONAL_API_KEY environment variable, then the OS credential
store (Windows Credential Manager, macOS Keychain, Secret Service on Linux).
The key is never written to a file by this package.
"""

from __future__ import annotations

import logging
import os

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from .config import ENV_API_KEY, KEYRING_SERVICE, KEYRING_USERNAME
from .redact import REDACTOR

log = logging.getLogger(__name__)


class MissingApiKeyError(RuntimeError):
    """No Garmin Personal API key is configured."""

    def __init__(self) -> None:
        super().__init__(
            "No Garmin Personal API key found. "
            f"Run 'garmin-connector set-key' or set {ENV_API_KEY}."
        )


def load_api_key() -> str:
    """Return the API key, or raise MissingApiKeyError."""
    key = os.environ.get(ENV_API_KEY, "").strip()
    if not key:
        try:
            key = (keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME) or "").strip()
        except KeyringError as exc:
            log.warning("Credential store unavailable: %s", type(exc).__name__)
            key = ""
    if not key:
        raise MissingApiKeyError()
    REDACTOR.register(key)
    return key


def store_api_key(key: str) -> None:
    """Save the key in the OS credential store."""
    key = key.strip()
    if not key:
        raise ValueError("Empty key")
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, key)


def delete_api_key() -> bool:
    """Remove the key from the OS credential store. Returns False if none was stored."""
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except PasswordDeleteError:
        return False
    return True
