"""HTTP client for beatmap mirror sources with error handling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

import httpx
import structlog

from osu_server.domain.beatmaps import (
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_CONTENT_DISPOSITION_FILENAME = re.compile(
    r'filename\s*=\s*"([^"]*)"',
    re.IGNORECASE,
)

_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)

_TEMPORARY_STATUSES: frozenset[int] = frozenset(
    {HTTPStatus.TOO_MANY_REQUESTS} | set(range(500, 600))
)


def _category_for_status(status_code: int) -> BeatmapSourceErrorCategory:
    if status_code == HTTPStatus.TOO_MANY_REQUESTS:
        return BeatmapSourceErrorCategory.RATE_LIMITED
    if status_code in _TEMPORARY_STATUSES:
        return BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE
    if status_code == HTTPStatus.UNAUTHORIZED:
        return BeatmapSourceErrorCategory.UNAUTHORIZED
    if status_code == HTTPStatus.NOT_FOUND:
        return BeatmapSourceErrorCategory.NOT_FOUND
    return BeatmapSourceErrorCategory.INVALID_RESPONSE


def _error_from_response(
    response: httpx.Response,
    *,
    source: str,
    lookup_key: str,
) -> BeatmapSourceError:
    category = _category_for_status(response.status_code)

    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        log_fields: dict[str, object] = {"source": source, "lookup_key": lookup_key}
        beatmap_id = _beatmap_id_from_lookup_key(lookup_key)
        if beatmap_id is not None:
            log_fields["beatmap_id"] = beatmap_id
        logger.warning("beatmap_source_rate_limited", **log_fields)

    return BeatmapSourceError(
        category=category,
        source=source,
        lookup_key=lookup_key,
        message=f"HTTP {response.status_code} from {source} for {lookup_key}",
    )


def _beatmap_id_from_lookup_key(lookup_key: str) -> int | None:
    prefix = "beatmap_id="
    if not lookup_key.startswith(prefix):
        return None

    raw_beatmap_id = lookup_key.removeprefix(prefix)
    try:
        return int(raw_beatmap_id)
    except ValueError:
        return None


def _error_from_exception(
    exc: Exception,
    *,
    source: str,
    lookup_key: str,
    category: BeatmapSourceErrorCategory,
) -> BeatmapSourceError:
    return BeatmapSourceError(
        category=category,
        source=source,
        lookup_key=lookup_key,
        message=f"{type(exc).__name__} from {source} for {lookup_key}: {exc}",
        original_error=exc,
    )


def _extract_filename(headers: Mapping[str, str]) -> str | None:
    disposition = headers.get("Content-Disposition")
    if disposition is None:
        return None
    match = _CONTENT_DISPOSITION_FILENAME.search(disposition)
    return match.group(1) if match else None


def is_permanent_error(error: BeatmapSourceError) -> bool:
    """Check if error is permanent (404, 401) vs temporary (rate limit, 5xx, timeout)."""
    return error.category in {
        BeatmapSourceErrorCategory.NOT_FOUND,
        BeatmapSourceErrorCategory.UNAUTHORIZED,
    }


@dataclass(slots=True)
class HttpFetchResult:
    """Raw HTTP fetch result."""

    content: bytes
    filename: str | None


class BeatmapHttpClient:
    """HTTP client for beatmap mirror sources."""

    _client: httpx.AsyncClient | None

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    def get_client(self) -> httpx.AsyncClient:
        """Get the underlying httpx client for custom requests."""
        return self._get_client()

    async def fetch(
        self,
        url: str,
        *,
        source: str,
        lookup_key: str,
    ) -> HttpFetchResult:
        """Fetch content from URL.

        Args:
            url: URL to fetch
            source: Source label for error messages
            lookup_key: Lookup key for error messages

        Returns:
            HttpFetchResult with content and optional filename

        Raises:
            BeatmapSourceError: On HTTP error or connection failure
        """
        client = self._get_client()

        try:
            response = await client.get(url, follow_redirects=True)
        except _TRANSIENT_EXCEPTIONS as exc:
            category = (
                BeatmapSourceErrorCategory.TIMEOUT
                if isinstance(exc, httpx.TimeoutException)
                else BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE
            )
            raise _error_from_exception(
                exc,
                source=source,
                lookup_key=lookup_key,
                category=category,
            ) from exc

        if response.status_code == HTTPStatus.OK:
            filename = _extract_filename(response.headers)
            return HttpFetchResult(content=response.content, filename=filename)

        raise _error_from_response(response, source=source, lookup_key=lookup_key)

    async def fetch_json(
        self,
        url: str,
        *,
        source: str,
        lookup_key: str,
    ) -> dict[str, object] | list[object]:
        """Fetch JSON from URL.

        Args:
            url: URL to fetch
            source: Source label for error messages
            lookup_key: Lookup key for error messages

        Returns:
            Parsed JSON object or array

        Raises:
            BeatmapSourceError: On HTTP error, connection failure, or JSON decode error
        """
        result = await self.fetch(url, source=source, lookup_key=lookup_key)
        try:
            return httpx.Response(200, content=result.content).json()  # pyright: ignore[reportAny]
        except Exception as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source,
                lookup_key=lookup_key,
                message=f"JSON decode error from {source}: {exc}",
                original_error=exc,
            ) from exc
