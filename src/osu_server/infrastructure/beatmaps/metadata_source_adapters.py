"""Beatmap metadata provider services."""

from __future__ import annotations

import time
from http import HTTPStatus
from typing import TYPE_CHECKING, cast
from urllib.parse import urlencode, urlparse

import httpx
import structlog

from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
    BeatmapSourceVerification,
)
from osu_server.infrastructure.beatmaps.mappers import (
    beatmap_json_to_snapshot,
    beatmap_v1_json_to_snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from osu_server.domain.beatmaps import BeatmapsetSnapshot
    from osu_server.infrastructure.http.interfaces import BeatmapHttpClient

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class InMemoryBeatmapMetadataProvider:
    """Stores provider snapshots in dicts for test environments."""

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


class OsuApiMetadataProviderService:
    """Official osu! API v2 metadata provider with OAuth authentication."""

    _client_id: str
    _client_secret: str
    _base_url: str
    _token_url: str
    _http_client: BeatmapHttpClient

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        http_client: BeatmapHttpClient,
        base_url: str = "https://osu.ppy.sh/api/v2",
        token_url: str = "https://osu.ppy.sh/oauth/token",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._token_url = token_url
        self._http_client = http_client
        self._access_token: str | None = None
        self._token_expiry: float = 0.0

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        return await self._lookup(f"/beatmaps/{beatmap_id}", lookup_key=str(beatmap_id))

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        return await self._lookup(f"/beatmapsets/{beatmapset_id}", lookup_key=str(beatmapset_id))

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        return await self._lookup(
            f"/beatmaps/lookup?checksum={checksum_md5}",
            lookup_key=checksum_md5,
        )

    async def _lookup(self, path: str, *, lookup_key: str) -> BeatmapsetSnapshot | None:

        source_label = "osu_api_v2"
        token = await self._get_token()
        url = f"{self._base_url}{path}"

        client = self._http_client.get_client()
        try:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TIMEOUT,
                source=source_label,
                lookup_key=lookup_key,
                message=f"Request failed: {exc}",
                original_error=exc,
            ) from exc
        except Exception as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
                source=source_label,
                lookup_key=lookup_key,
                message=f"Request failed: {exc}",
                original_error=exc,
            ) from exc

        if response.status_code == HTTPStatus.OK:
            try:
                parsed: object = response.json()
            except Exception as exc:
                raise BeatmapSourceError(
                    category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                    source=source_label,
                    lookup_key=lookup_key,
                    message=f"Invalid JSON from {source_label}",
                    original_error=exc,
                ) from exc
            if not isinstance(parsed, dict):
                actual = type(parsed).__name__
                raise BeatmapSourceError(
                    category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                    source=source_label,
                    lookup_key=lookup_key,
                    message=f"Expected JSON object from {source_label}, got {actual}",
                )
            return beatmap_json_to_snapshot(cast("dict[str, object]", parsed))

        if response.status_code == HTTPStatus.NOT_FOUND:
            return None

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.UNAUTHORIZED,
                source=source_label,
                lookup_key=lookup_key,
                message=f"HTTP {response.status_code} from {source_label}",
            )

        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.RATE_LIMITED,
                source=source_label,
                lookup_key=lookup_key,
                message=f"HTTP {response.status_code} from {source_label}",
            )

        if 500 <= response.status_code < 600:  # noqa: PLR2004
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
                source=source_label,
                lookup_key=lookup_key,
                message=f"HTTP {response.status_code} from {source_label}",
            )

        raise BeatmapSourceError(
            category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
            source=source_label,
            lookup_key=lookup_key,
            message=f"HTTP {response.status_code} from {source_label}",
        )

    async def _get_token(self) -> str:
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token

        source_label = "osu_oauth"
        client = self._http_client.get_client()

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
        except httpx.TimeoutException as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TIMEOUT,
                source=source_label,
                lookup_key="token",
                message=f"Token request timeout: {exc}",
                original_error=exc,
            ) from exc
        except Exception as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
                source=source_label,
                lookup_key="token",
                message=f"Token request failed: {exc}",
                original_error=exc,
            ) from exc

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.UNAUTHORIZED,
                source=source_label,
                lookup_key="token",
                message=f"Token endpoint returned {response.status_code}",
            )

        if 500 <= response.status_code < 600:  # noqa: PLR2004
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
                source=source_label,
                lookup_key="token",
                message=f"Token endpoint returned {response.status_code}",
            )

        if response.status_code != HTTPStatus.OK:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source_label,
                lookup_key="token",
                message=f"Token endpoint returned {response.status_code}",
            )

        try:
            parsed: object = response.json()
        except Exception as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source_label,
                lookup_key="token",
                message=f"Invalid JSON from token endpoint: {exc}",
                original_error=exc,
            ) from exc

        if not isinstance(parsed, dict):
            actual = type(parsed).__name__
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source_label,
                lookup_key="token",
                message=f"Expected JSON object from token endpoint, got {actual}",
            )
        data = cast("Mapping[str, object]", parsed)

        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source_label,
                lookup_key="token",
                message="Token response missing valid access_token",
            )

        expires_in = data.get("expires_in", 86400)
        try:
            expires_seconds = float(cast("int | float | str", expires_in))
        except (TypeError, ValueError) as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source_label,
                lookup_key="token",
                message="Token response has invalid expires_in",
                original_error=exc,
            ) from exc

        self._access_token = access_token
        self._token_expiry = time.time() + expires_seconds - 60
        return self._access_token


def _source_label(base_url: str) -> str:
    hostname = urlparse(base_url).hostname or base_url
    return f"mirror[{hostname}]"


def _is_nerinyan_url(base_url: str) -> bool:
    hostname = urlparse(base_url).hostname
    return hostname is not None and "nerinyan" in hostname.lower()


class MirrorMetadataProviderService:
    """Community mirror metadata provider (Nerinyan, Chimu, Kitsu, etc.)."""

    _base_urls: tuple[str, ...]
    _api_version: str
    _http_client: BeatmapHttpClient

    def __init__(
        self,
        *,
        http_client: BeatmapHttpClient,
        base_url: str | None = None,
        base_urls: Sequence[str] | None = None,
        api_version: str = "v2",
    ) -> None:
        self._base_urls = _normalize_base_urls(base_url=base_url, base_urls=base_urls)
        self._api_version = api_version
        self._http_client = http_client

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        return await self._lookup(
            f"/b/{beatmap_id}",
            lookup_key=str(beatmap_id),
            nerinyan_params={"b": str(beatmap_id)},
        )

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        return await self._lookup(
            f"/s/{beatmapset_id}",
            lookup_key=str(beatmapset_id),
            nerinyan_params={"s": str(beatmapset_id)},
        )

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        return await self._lookup(
            f"/hash/{checksum_md5}",
            lookup_key=checksum_md5,
            nerinyan_params={"h": checksum_md5},
        )

    async def _lookup(
        self,
        path: str,
        *,
        lookup_key: str,
        nerinyan_params: Mapping[str, str],
    ) -> BeatmapsetSnapshot | None:
        if not self._base_urls:
            return None

        last_error: BeatmapSourceError | None = None
        for base_url in self._base_urls:
            source_label = _source_label(base_url)
            is_nerinyan = _is_nerinyan_url(base_url)
            url = (
                f"{base_url}/v1/get_beatmaps?{urlencode(nerinyan_params)}"
                if is_nerinyan
                else f"{base_url}/{self._api_version}{path}"
            )
            try:
                data = await self._http_client.fetch_json(
                    url,
                    source=source_label,
                    lookup_key=lookup_key,
                )
            except BeatmapSourceError as exc:
                if exc.category == BeatmapSourceErrorCategory.NOT_FOUND:
                    continue
                last_error = exc
                continue

            if is_nerinyan and isinstance(data, list):
                return beatmap_v1_json_to_snapshot(
                    cast("Sequence[Mapping[str, object]]", data),
                    source=BeatmapMetadataSource.MIRROR,
                    verification=BeatmapSourceVerification.UNVERIFIED,
                )

            if isinstance(data, dict):
                data_dict: dict[str, object] = data
                if is_nerinyan:
                    return beatmap_v1_json_to_snapshot(
                        [data_dict],
                        source=BeatmapMetadataSource.MIRROR,
                        verification=BeatmapSourceVerification.UNVERIFIED,
                    )
                return beatmap_json_to_snapshot(
                    data_dict,
                    source=BeatmapMetadataSource.MIRROR,
                    verification=BeatmapSourceVerification.UNVERIFIED,
                )

            last_error = BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source_label,
                lookup_key=lookup_key,
                message=f"Unexpected JSON from {source_label}",
            )

        if last_error is not None:
            raise last_error
        return None


def _normalize_base_urls(
    *,
    base_url: str | None,
    base_urls: Sequence[str] | None,
) -> tuple[str, ...]:
    raw_urls: Sequence[str]
    if base_urls is not None:
        raw_urls = base_urls if base_url is None else (*base_urls, base_url)
    elif base_url is not None:
        raw_urls = (base_url,)
    else:
        raw_urls = ()

    return tuple(normalized for url in raw_urls if (normalized := url.strip().rstrip("/")))
