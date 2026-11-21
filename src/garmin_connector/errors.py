"""Exceptions raised to tool callers. Messages never contain the key or token."""

from __future__ import annotations


class GarminError(RuntimeError):
    """Base class for errors talking to Garmin."""


class GarminAuthError(GarminError):
    """The key could not be swapped for a token, or the token was refused."""


class GarminApiError(GarminError):
    """A data request failed."""

    def __init__(self, status: int, path: str) -> None:
        self.status = status
        self.path = path
        super().__init__(f"Garmin returned HTTP {status} for {path}")
