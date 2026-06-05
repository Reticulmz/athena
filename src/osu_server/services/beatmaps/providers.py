"""Concrete ``BeatmapMetadataProvider`` implementations.

Provides:
    * ``InMemoryBeatmapMetadataProvider`` -- stores snapshots in memory for test environments.
    * ``OsuApiMetadataProvider`` -- official osu! API v2 metadata provider.
    * ``MirrorMetadataProvider`` -- placeholder mirror API provider (not yet implemented).
"""

from __future__ import annotations

import time
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import httpx
import structlog

from osu_server.infrastructure.beatmaps.errors import (
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
)
from osu_server.services.beatmaps.mappers import beatmap_json_to_snapshot

if TYPE_CHECKING:
    from osu_server.domain.beatmap import BeatmapsetSnapshot

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

# ---------------------------------------------------------------------------
# Shared helpers (same patterns as file_sources.py)
# ---------------------------------------------------------------------------

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


class InMemoryBeatmapMetadataProvider:
    """Stores ``BeatmapsetSnapshot`` data in dicts for test environments.

    Snapshots can be preloaded via ``add_snapshot()`` so that composition
    tests and integration tests can arrange known beatmap data without
    real external credentials.
    """

    def __init__(self) -> None:
        self._by_beatmap_id: dict[int, BeatmapsetSnapshot] = {}
        self._by_beatmapset_id: dict[int, BeatmapsetSnapshot] = {}
        self._checksum_to_beatmap_id: dict[str, int] = {}

    def add_snapshot(self, snapshot: BeatmapsetSnapshot) -> None:
        """Preload a snapshot so lookups return it."""
        self._by_beatmapset_id[snapshot.beatmapset_id] = snapshot
        for bm in snapshot.beatmaps:
            self._by_beatmap_id[bm.beatmap_id] = snapshot
            if bm.checksum_md5:
                self._checksum_to_beatmap_id[bm.checksum_md5] = bm.beatmap_id

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        return self._by_beatmap_id.get(beatmap_id)

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        return self._by_beatmapset_id.get(beatmapset_id)

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        beatmap_id = self._checksum_to_beatmap_id.get(checksum_md5)
        if beatmap_id is None:
            return None
        return self._by_beatmap_id.get(beatmap_id)


class OsuApiMetadataProvider:
    """Official osu! API v2 metadata provider.

    Authenticates via OAuth2 client-credentials and fetches beatmap metadata
    from the public osu! API v2 endpoints.  Errors are normalised to
    ``BeatmapSourceError`` categories following the same pattern as the file
    source provider.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        base_url: str = "https://osu.ppy.sh/api/v2",
        token_url: str = "https://osu.ppy.sh/oauth/token",
    ) -> None:
        self._client_id: str = client_id
        self._client_secret: str = client_secret
        self._base_url: str = base_url.rstrip("/")
        self._token_url: str = token_url
        self._access_token: str | None = None
        self._token_expiry: float = 0.0
        self._httpx_client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Public lookup interface
    # ------------------------------------------------------------------

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        return await self._lookup(f"/beatmaps/{beatmap_id}", lookup_key=str(beatmap_id))

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        return await self._lookup(
            f"/beatmapsets/{beatmapset_id}",
            lookup_key=str(beatmapset_id),
        )

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        return await self._lookup(
            f"/beatmaps/lookup?checksum={checksum_md5}",
            lookup_key=checksum_md5,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _lookup(
        self,
        path: str,
        *,
        lookup_key: str,
    ) -> BeatmapsetSnapshot | None:
        source_label = "osu_api_v2"
        client = self._get_client()

        try:
            token = await self._get_token()
            response = await client.get(
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
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

        if response.status_code == httpx.codes.OK:
            try:
                data = cast("dict[str, object]", response.json())
            except Exception as exc:
                raise BeatmapSourceError(
                    category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                    source=source_label,
                    lookup_key=lookup_key,
                    message=f"Invalid JSON from {source_label} for {lookup_key}",
                    original_error=exc,
                ) from exc
            return beatmap_json_to_snapshot(data)

        if response.status_code == httpx.codes.NOT_FOUND:
            return None

        raise _error_from_response(
            response,
            source=source_label,
            lookup_key=lookup_key,
        )

    # ------------------------------------------------------------------
    # httpx client (lazy, same pattern as file_sources.py)
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        if self._httpx_client is not None:
            return self._httpx_client
        client = httpx.AsyncClient()
        object.__setattr__(self, "_httpx_client", client)
        return client

    # ------------------------------------------------------------------
    # OAuth2 token management
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        if self._access_token is not None and time.monotonic() < self._token_expiry:
            return self._access_token

        client = self._get_client()

        try:
            response = await client.post(
                self._token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                    "scope": "public",
                },
            )
        except _TRANSIENT_EXCEPTIONS as exc:
            category = (
                BeatmapSourceErrorCategory.TIMEOUT
                if isinstance(exc, httpx.TimeoutException)
                else BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE
            )
            raise _error_from_exception(
                exc,
                source="osu_oauth",
                lookup_key="token",
                category=category,
            ) from exc

        if response.status_code != httpx.codes.OK:
            raise _error_from_response(
                response,
                source="osu_oauth",
                lookup_key="token",
            )

        try:
            token_data = cast("dict[str, object]", response.json())
            access_token = cast("str", token_data["access_token"])
            # Schedule refresh 60 s before expiry; default to 1 h if the field
            # is missing.
            expires_in = int(cast("float", token_data.get("expires_in", 3600)))
            self._token_expiry = time.monotonic() + max(0, expires_in - 60)
            self._access_token = access_token
        except (KeyError, TypeError, ValueError) as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source="osu_oauth",
                lookup_key="token",
                message="Invalid OAuth2 token response",
                original_error=exc,
            ) from exc

        return access_token


class MirrorMetadataProvider:
    """Placeholder mirror API metadata provider.

    Returns ``None`` for all lookups.  Real mirror integration will be added
    once the mirror endpoint configuration is finalized.
    """

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        logger.debug("mirror_metadata_provider_not_implemented", beatmap_id=beatmap_id)
        return None

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        logger.debug("mirror_metadata_provider_not_implemented", beatmapset_id=beatmapset_id)
        return None

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        logger.debug("mirror_metadata_provider_not_implemented", checksum_md5=checksum_md5)
        return None
