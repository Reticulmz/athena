"""Composite .osu file source provider with fallback priority.

Direct sources (osu_current, osu_legacy) are tried before community mirrors.
Temporary failures (429, 5xx, timeout, connection error) trigger fallback;
permanent failures (404, 401, 403) do not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from http import HTTPStatus

import httpx
import structlog

from osu_server.infrastructure.beatmaps.contracts import (
    BeatmapFileSource,
    OsuFileFetchResult,
)
from osu_server.infrastructure.beatmaps.errors import (
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_CONTENT_DISPOSITION_FILENAME = re.compile(
    r'filename\s*=\s*"([^"]*)"',
    re.IGNORECASE,
)

# Status codes that signal a temporary condition where retrying a different
# source is reasonable.
_TEMPORARY_STATUSES: frozenset[int] = frozenset(
    {HTTPStatus.TOO_MANY_REQUESTS} | set(range(500, 600))
)

# httpx exceptions that represent transient transport-level failures.
_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)


def _extract_filename(response: httpx.Response) -> str | None:
    """Extract filename from a Content-Disposition header, if present."""
    disposition: str | None = response.headers.get("Content-Disposition")  # pyright: ignore[reportAny]
    if disposition is None:
        return None
    match = _CONTENT_DISPOSITION_FILENAME.search(disposition)
    if match is None:
        return None
    return match.group(1)


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
    return BeatmapSourceError(
        category=category,
        source=source,
        lookup_key=lookup_key,
        message=f"HTTP {response.status_code} from {source} for {lookup_key}",
    )


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


def _is_permanent(exc: BeatmapSourceError) -> bool:
    return exc.category in {
        BeatmapSourceErrorCategory.NOT_FOUND,
        BeatmapSourceErrorCategory.UNAUTHORIZED,
    }


# ---------------------------------------------------------------------------
# Internal signal exception -- carries a successful result up the call stack
# ---------------------------------------------------------------------------


class _FoundError(Exception):
    """Signal that a source returned a successful fetch result."""

    result: OsuFileFetchResult

    def __init__(self, result: OsuFileFetchResult) -> None:
        super().__init__()
        self.result = result


# ---------------------------------------------------------------------------
# Composite provider
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CompositeBeatmapFileProvider:
    """Fetches .osu file bytes with source priority: current > legacy > mirror.

    Temporary failures (rate limit, timeout, 5xx, connection errors) trigger
    a fallback attempt on the next source.  Permanent failures like 404 do
    not automatically fall through to mirrors.
    """

    osu_current_url_template: str = "https://osu.ppy.sh/osu/{beatmap_id}"
    osu_legacy_url_template: str = "https://old.ppy.sh/osu/{beatmap_id}"
    mirror_url_templates: list[str] = field(default_factory=list)
    httpx_client: httpx.AsyncClient | None = field(default=None, repr=False)

    def _get_client(self) -> httpx.AsyncClient:
        if self.httpx_client is not None:
            return self.httpx_client
        client = httpx.AsyncClient()
        object.__setattr__(self, "httpx_client", client)
        return client

    async def fetch_osu_file(self, beatmap_id: int) -> OsuFileFetchResult:
        client = self._get_client()
        lookup_key = f"beatmap_id={beatmap_id}"

        # Phase 1 -- try direct sources.  _FoundError carries success.
        try:
            await self._try_direct_sources(client, beatmap_id, lookup_key)
        except _FoundError as found:
            return found.result
        except BeatmapSourceError as direct_error:
            if _is_permanent(direct_error):
                raise  # permanent: skip mirrors
            # temporary: fall through to mirrors

        # Phase 2 -- try community mirrors
        try:
            await self._try_mirror_sources(client, beatmap_id, lookup_key)
        except _FoundError as found:
            logger.info(
                "beatmap_mirror_fallback_used",
                source_type="file",
                beatmap_id=beatmap_id,
                source=found.result.source.value,
            )
            return found.result
        except BeatmapSourceError:
            raise

        msg = f"All .osu file sources exhausted for beatmap_id={beatmap_id}"
        raise BeatmapSourceError(
            category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
            source="composite",
            lookup_key=lookup_key,
            message=msg,
        )

    # ------------------------------------------------------------------
    # Per-source fetch
    # ------------------------------------------------------------------

    async def _try_fetch(
        self,
        client: httpx.AsyncClient,
        *,
        url_template: str,
        beatmap_id: int,
        source: BeatmapFileSource,
        source_label: str,
        lookup_key: str,
    ) -> OsuFileFetchResult:
        url = url_template.format(beatmap_id=beatmap_id)
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
                source=source_label,
                lookup_key=lookup_key,
                category=category,
            ) from exc

        if response.status_code == HTTPStatus.OK:
            filename = _extract_filename(response)
            return OsuFileFetchResult(
                beatmap_id=beatmap_id,
                body=response.content,
                source=source,
                original_filename=filename,
            )

        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            logger.warning(
                "beatmap_source_rate_limited",
                source=source_label,
                beatmap_id=beatmap_id,
            )

        raise _error_from_response(
            response,
            source=source_label,
            lookup_key=lookup_key,
        )

    # ------------------------------------------------------------------
    # Direct source phase
    # ------------------------------------------------------------------

    async def _try_direct_sources(
        self,
        client: httpx.AsyncClient,
        beatmap_id: int,
        lookup_key: str,
    ) -> None:
        """Try osu_current then osu_legacy.

        Raises:
            _FoundError: A source returned a successful result.
            BeatmapSourceError: All direct sources failed.  Permanent failures
                (404 / 401) propagate immediately; temporary failures only
                propagate after both sources are exhausted.
        """
        last_error: BeatmapSourceError | None = None

        for url_template, source, label in (
            (self.osu_current_url_template, BeatmapFileSource.OSU_CURRENT, "osu_current"),
            (self.osu_legacy_url_template, BeatmapFileSource.OSU_LEGACY, "osu_legacy"),
        ):
            try:
                result = await self._try_fetch(
                    client,
                    url_template=url_template,
                    beatmap_id=beatmap_id,
                    source=source,
                    source_label=label,
                    lookup_key=lookup_key,
                )
                raise _FoundError(result)
            except BeatmapSourceError as exc:
                last_error = exc
                if _is_permanent(exc):
                    raise  # permanent: stop trying more sources

        # All direct sources produced temporary errors only
        assert last_error is not None
        raise last_error

    # ------------------------------------------------------------------
    # Mirror source phase
    # ------------------------------------------------------------------

    async def _try_mirror_sources(
        self,
        client: httpx.AsyncClient,
        beatmap_id: int,
        lookup_key: str,
    ) -> None:
        """Try community mirrors in order.

        Raises:
            _FoundError: A mirror returned a successful result.
            BeatmapSourceError: All mirrors failed.
        """
        last_error: BeatmapSourceError | None = None
        for idx, url_template in enumerate(self.mirror_url_templates):
            label = f"community_mirror[{idx}]"
            try:
                result = await self._try_fetch(
                    client,
                    url_template=url_template,
                    beatmap_id=beatmap_id,
                    source=BeatmapFileSource.COMMUNITY_MIRROR,
                    source_label=label,
                    lookup_key=lookup_key,
                )
                raise _FoundError(result)
            except BeatmapSourceError as exc:
                last_error = exc
                if _is_permanent(exc):
                    raise

        if last_error is not None:
            raise last_error
