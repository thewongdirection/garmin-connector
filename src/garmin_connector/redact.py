"""Keep the API key and access token out of logs and error messages."""

from __future__ import annotations

import logging
import re
import threading

_MASK = "***"
_AUTH_PATTERN = re.compile(r"(?i)\b(ApiKey|Bearer)\s+[^\s\"',;]+")
_MIN_SECRET_LENGTH = 6


class Redactor:
    """Holds known secret values and masks them in any text."""

    def __init__(self) -> None:
        self._secrets: set[str] = set()
        self._lock = threading.Lock()

    def register(self, secret: str | None) -> None:
        if secret and len(secret) >= _MIN_SECRET_LENGTH:
            with self._lock:
                self._secrets.add(secret)

    def redact(self, text: str) -> str:
        with self._lock:
            secrets = sorted(self._secrets, key=len, reverse=True)
        for secret in secrets:
            text = text.replace(secret, _MASK)
        return _AUTH_PATTERN.sub(lambda m: f"{m.group(1)} {_MASK}", text)


REDACTOR = Redactor()


class RedactingFilter(logging.Filter):
    """Logging filter that masks secrets in the fully formatted message."""

    def __init__(self, redactor: Redactor = REDACTOR) -> None:
        super().__init__()
        self._redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{logging.Formatter().formatException(record.exc_info)}"
            record.exc_info = None
            record.exc_text = None
        record.msg = self._redactor.redact(message)
        record.args = None
        return True
