"""Tests for OsuApiMetadataProvider -- real osu! API v2 integration.

Uses ``httpx.MockTransport`` to avoid real network calls.
"""

from __future__ import annotations

import httpx
import pytest

from osu_server.infrastructure.beatmaps.errors import (
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
)
from osu_server.infrastructure.beatmaps.providers import OsuApiMetadataProvider

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

_CLIENT_ID = "test-client-id"
_CLIENT_SECRET = "test-client-secret"
_BASE_URL = "https://osu.example.com/api/v2"
_TOKEN_URL = "https://osu.example.com/oauth/token"

_ACCESS_TOKEN = "mock-access-token"
_TOKEN_BODY: dict[str, object] = {"access_token": _ACCESS_TOKEN, "expires_in": 3600}

_BEATMAPSET_BODY: dict[str, object] = {
    "id": 1,
    "artist": "Test Artist",
    "title": "Test Title",
    "creator": "Test Creator",
    "status": "ranked",
    "beatmaps": [
        {
            "id": 100,
            "beatmapset_id": 1,
            "checksum": "a" * 32,
            "mode": "osu",
            "version": "Normal",
            "status": "ranked",
            "total_length": 120,
            "hit_length": 90,
            "max_combo": 500,
            "bpm": 180.0,
            "cs": 4.0,
            "accuracy": 8.0,
            "ar": 9.0,
            "drain": 6.0,
            "difficulty_rating": 5.5,
        }
    ],
}

_BEATMAP_BODY: dict[str, object] = {
    "id": 100,
    "beatmapset_id": 1,
    "checksum": "a" * 32,
    "mode": "osu",
    "version": "Normal",
    "status": "ranked",
    "total_length": 120,
    "hit_length": 90,
    "max_combo": 500,
    "bpm": 180.0,
    "cs": 4.0,
    "accuracy": 8.0,
    "ar": 9.0,
    "drain": 6.0,
    "difficulty_rating": 5.5,
    "beatmapset": {
        "id": 1,
        "artist": "Test Artist",
        "title": "Test Title",
        "creator": "Test Creator",
        "status": "ranked",
    },
}


# ---------------------------------------------------------------------------
# Mock transport helpers
# ---------------------------------------------------------------------------


def _make_transport(
    *,
    token_status: int = 200,
    token_exc: type[Exception] | None = None,
    data_status: int = 200,
    data_body: dict[str, object] | None = None,
    data_raw: str | None = None,
    data_exc: type[Exception] | None = None,
) -> httpx.MockTransport:
    """Build a ``httpx.MockTransport`` handling token + data endpoints."""

    def handler(request: httpx.Request) -> httpx.Response:
        if token_exc is not None:
            raise token_exc("token error")
        if data_exc is not None:
            raise data_exc("data error")

        url = str(request.url)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType, reportAttributeAccessIssue]
        if "/oauth/token" in url:
            return httpx.Response(token_status, json=_TOKEN_BODY, request=request)

        if data_raw is not None:
            return httpx.Response(data_status, content=data_raw.encode(), request=request)

        body = data_body if data_body is not None else _BEATMAPSET_BODY
        return httpx.Response(data_status, json=body, request=request)

    return httpx.MockTransport(handler)


def _make_provider(transport: httpx.MockTransport) -> OsuApiMetadataProvider:
    """Create a provider with a mock transport injected."""
    provider = OsuApiMetadataProvider(
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
        base_url=_BASE_URL,
        token_url=_TOKEN_URL,
    )
    provider._httpx_client = httpx.AsyncClient(transport=transport)  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    return provider


# ---------------------------------------------------------------------------
# OAuth2 token acquisition
# ---------------------------------------------------------------------------


class TestTokenAcquisition:
    """OAuth2 client_credentials flow and token caching."""

    async def test_acquires_token_on_first_lookup(self) -> None:
        transport = _make_transport()
        provider = _make_provider(transport)

        result = await provider.lookup_by_beatmapset_id(1)

        assert result is not None
        assert result.beatmapset_id == 1

    async def test_caches_token_across_lookups(self) -> None:
        transport = _make_transport()
        provider = _make_provider(transport)

        _ = await provider.lookup_by_beatmapset_id(1)
        # Second call reuses cached token; both should succeed
        result = await provider.lookup_by_beatmap_id(100)

        assert result is not None
        assert result.beatmapset_id == 1

    async def test_token_endpoint_returns_error(self) -> None:
        transport = _make_transport(token_status=500)
        provider = _make_provider(transport)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(1)
        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE
        assert exc_info.value.source == "osu_oauth"

    async def test_token_endpoint_timeout(self) -> None:
        transport = _make_transport(token_exc=httpx.TimeoutException)
        provider = _make_provider(transport)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(1)
        assert exc_info.value.category is BeatmapSourceErrorCategory.TIMEOUT
        assert exc_info.value.source == "osu_oauth"

    async def test_token_endpoint_connect_error(self) -> None:
        transport = _make_transport(token_exc=httpx.ConnectError)
        provider = _make_provider(transport)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(1)
        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE


# ---------------------------------------------------------------------------
# Successful lookups
# ---------------------------------------------------------------------------


class TestSuccessfulLookups:
    """Happy-path metadata resolution for all three lookup methods."""

    async def test_lookup_by_beatmap_id(self) -> None:
        transport = _make_transport(data_body=_BEATMAP_BODY)
        provider = _make_provider(transport)

        result = await provider.lookup_by_beatmap_id(100)

        assert result is not None
        assert result.beatmapset_id == 1
        assert len(result.beatmaps) == 1
        bm = result.beatmaps[0]
        assert bm.beatmap_id == 100
        assert bm.checksum_md5 == "a" * 32

    async def test_lookup_by_beatmapset_id(self) -> None:
        transport = _make_transport(data_body=_BEATMAPSET_BODY)
        provider = _make_provider(transport)

        result = await provider.lookup_by_beatmapset_id(1)

        assert result is not None
        assert result.beatmapset_id == 1
        assert result.artist == "Test Artist"
        assert result.title == "Test Title"

    async def test_lookup_by_checksum(self) -> None:
        transport = _make_transport(data_body=_BEATMAP_BODY)
        provider = _make_provider(transport)

        result = await provider.lookup_by_checksum("a" * 32)

        assert result is not None
        assert result.beatmaps[0].checksum_md5 == "a" * 32


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------


class TestNotFound:
    """404 returns ``None`` without raising."""

    async def test_beatmap_id_404_returns_none(self) -> None:
        transport = _make_transport(data_status=404)
        provider = _make_provider(transport)

        result = await provider.lookup_by_beatmap_id(999)
        assert result is None

    async def test_beatmapset_id_404_returns_none(self) -> None:
        transport = _make_transport(data_status=404)
        provider = _make_provider(transport)

        result = await provider.lookup_by_beatmapset_id(999)
        assert result is None

    async def test_checksum_404_returns_none(self) -> None:
        transport = _make_transport(data_status=404)
        provider = _make_provider(transport)

        result = await provider.lookup_by_checksum("f" * 32)
        assert result is None


# ---------------------------------------------------------------------------
# Error responses
# ---------------------------------------------------------------------------


class TestErrorResponses:
    """HTTP error status codes map to ``BeatmapSourceErrorCategory``."""

    async def test_401_raises_unauthorized(self) -> None:
        transport = _make_transport(data_status=401)
        provider = _make_provider(transport)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmap_id(100)
        assert exc_info.value.category is BeatmapSourceErrorCategory.UNAUTHORIZED

    async def test_429_raises_rate_limited(self) -> None:
        transport = _make_transport(data_status=429)
        provider = _make_provider(transport)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmap_id(100)
        assert exc_info.value.category is BeatmapSourceErrorCategory.RATE_LIMITED

    async def test_5xx_raises_temporary_unavailable(self) -> None:
        transport = _make_transport(data_status=503)
        provider = _make_provider(transport)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmap_id(100)
        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE

    async def test_invalid_json_raises(self) -> None:
        transport = _make_transport(data_status=200, data_raw="not json")
        provider = _make_provider(transport)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmap_id(100)
        assert exc_info.value.category is BeatmapSourceErrorCategory.INVALID_RESPONSE


class TestTimeoutErrors:
    """Transient HTTP exceptions are classified correctly."""

    async def test_timeout_on_data_request(self) -> None:
        transport = _make_transport(data_exc=httpx.TimeoutException)
        provider = _make_provider(transport)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmap_id(100)
        assert exc_info.value.category is BeatmapSourceErrorCategory.TIMEOUT

    async def test_connect_error_on_data_request(self) -> None:
        transport = _make_transport(data_exc=httpx.ConnectError)
        provider = _make_provider(transport)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmap_id(100)
        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE
