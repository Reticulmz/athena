"""Source failure categories for beatmap metadata providers."""

from __future__ import annotations

from enum import StrEnum


class BeatmapSourceErrorCategory(StrEnum):
    """Normalized failure categories for beatmap metadata sources."""

    CONFIGURATION = "configuration"
    UNAUTHORIZED = "unauthorized"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    TEMPORARY_UNAVAILABLE = "temporary_unavailable"
    NOT_FOUND = "not_found"
    INVALID_RESPONSE = "invalid_response"


class BeatmapSourceError(RuntimeError):
    """Normalized error from a beatmap metadata source.

    Carries the category, source identifier, lookup key, and optional
    original exception for diagnostics.
    """

    category: BeatmapSourceErrorCategory
    source: str
    lookup_key: str
    original_error: Exception | None

    def __init__(
        self,
        *,
        category: BeatmapSourceErrorCategory,
        source: str,
        lookup_key: str,
        message: str,
        original_error: Exception | None = None,
    ) -> None:
        self.category = category
        self.source = source
        self.lookup_key = lookup_key
        self.original_error = original_error
        super().__init__(message)
