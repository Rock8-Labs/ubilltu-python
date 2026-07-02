"""Error types raised by the ubilltu client."""

from __future__ import annotations

from typing import Any, Optional


class UbilltuError(Exception):
    """Base class for all errors raised by the ubilltu client."""


class UbilltuApiError(UbilltuError):
    """Raised when the API returns a non-2xx response.

    ``body`` is the decoded JSON error payload when available
    (e.g. ``{"detail": ...}``).
    """

    def __init__(
        self, status_code: int, message: str, body: Optional[dict] = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"UbilltuApiError({self.status_code}): {self.args[0]}"


class UbilltuAuthError(UbilltuError):
    """Raised when an authenticated call is made before :meth:`login`."""

    def __init__(self, message: str = "Not authenticated — call login() first.") -> None:
        super().__init__(message)
