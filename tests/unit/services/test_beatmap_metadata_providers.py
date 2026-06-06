"""Tests for OsuApiMetadataProvider — osu! API v2 integration.

Uses httpx.MockTransport for deterministic HTTP simulation.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, cast

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

from osu_server.domain.beatmap import BeatmapRankStatus
from osu_server.infrastructure.beatmaps.contracts import BeatmapMetadataSourceName
from osu_server.infrastructure.beatmaps.errors import (
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
)
from osu_server.infrastructure.beatmaps.providers import OsuApiMetadataProvider

# ---------------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------------

_CLIENT_ID = "test_client"
_CLIENT_SECRET = "test_secret"
_TOKEN_URL = "https://osu.ppy.sh/oauth/token"
_BEATMAP_ID = 2000
_BEATMAPSET_ID = 1000
_CHECKSUM = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"

_TOKEN_RESPONSE_BODY = {
    "access_token": "tok_deadbeef",
    "expires_in": 3600,
}

_BEATMAPSET_RESPONSE_BODY = {
    "id": _BEATMAPSET_ID,
    "artist": "Camellia",
    "title": "Exit This Earth's Atomosphere",
    "creator": "Realazy",
    "artist_unicode": "かめるりあ",
    "title_unicode": None,
    "status": "ranked",
    "beatmaps": [
        {
            "id": _BEATMAP_ID,
            "beatmapset_id": _BEATMAPSET_ID,
            "checksum": _CHECKSUM,
            "mode": "osu",
            "version": "Another",
            "status": "ranked",
            "total_length": 200,
            "hit_length": 150,
            "max_combo": 1200,
            "bpm": 220.0,
            "cs": 4.2,
            "accuracy": 9.1,
            "ar": 10.3,
            "drain": 7.8,
            "difficulty_rating": 6.77,
        },
    ],
}

_BEATMAP_RESPONSE_BODY = {
    "id": _BEATMAP_ID,
    "beatmapset_id": _BEATMAPSET_ID,
    "checksum": _CHECKSUM,
    "mode": "osu",
    "version": "Another",
    "status": "ranked",
    "total_length": 200,
    "hit_length": 150,
    "max_combo": 1200,
    "bpm": 220.0,
    "cs": 4.2,
    "accuracy": 9.1,
    "ar": 10.3,
    "drain": 7.8,
    "difficulty_rating": 6.77,
    "beatmapset": {
        "id": _BEATMAPSET_ID,
        "artist": "Camellia",
        "title": "Exit This Earth's Atomosphere",
        "creator": "Realazy",
        "artist_unicode": "かめるりあ",
        "title_unicode": None,
        "status": "ranked",
    },
}


# ---------------------------------------------------------------------------
# Mock transport helpers
# ---------------------------------------------------------------------------


def _handler_for(
    *,
    api_status: int = 200,
    api_body: Mapping[str, object] | None = None,
    api_error: type[Exception] | None = None,
    token_status: int = 200,
    token_body: Mapping[str, object] | None = None,
    token_error: type[Exception] | None = None,
    token_count: int = 0,
):
    """Build a httpx.MockTransport handler function.

    Routes POST to _TOKEN_URL → token response, GET to _BASE_URL/* → API response.
    When *token_count* > 0, each token request returns ``tok_<N>`` with incrementing N.
    """

    _token_call_counter: int = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal _token_call_counter
        url_str = str(request.url)  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue, reportUnknownArgumentType]

        # -- Token endpoint (POST) --------------------------------------------
        if _TOKEN_URL in url_str and request.method == "POST":  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
            if token_error is not None:
                raise token_error("mock token error")
            if token_count > 0:
                # Return incrementing token values
                _token_call_counter += 1
                body = {"access_token": f"tok_{_token_call_counter:08x}", "expires_in": 3600}
            else:
                body = token_body if token_body is not None else _TOKEN_RESPONSE_BODY
            return httpx.Response(
                token_status,
                content=json.dumps(body).encode(),
                request=request,
            )

        # -- API endpoints (GET) ----------------------------------------------
        if api_error is not None:
            raise api_error("mock api error")
        body = api_body if api_body is not None else _BEATMAPSET_RESPONSE_BODY
        return httpx.Response(
            api_status,
            content=json.dumps(body).encode(),
            request=request,
        )

    return handle


def _make_provider(
    *,
    token_status: int = 200,
    token_body: Mapping[str, object] | None = None,
    api_status: int = 200,
    api_body: Mapping[str, object] | None = None,
    api_error: type[Exception] | None = None,
    token_error: type[Exception] | None = None,
    token_count: int = 0,
) -> OsuApiMetadataProvider:
    """Create an OsuApiMetadataProvider backed by a MockTransport."""
    handler = _handler_for(
        token_status=token_status,
        token_body=token_body,
        api_status=api_status,
        api_body=api_body,
        api_error=api_error,
        token_error=token_error,
        token_count=token_count,
    )
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    provider = OsuApiMetadataProvider(
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
    )
    provider._httpx_client = client  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    return provider


# ---------------------------------------------------------------------------
# lookup_by_beatmapset_id — success
# ---------------------------------------------------------------------------


class TestLookupByBeatmapsetId:
    async def test_returns_snapshot_on_success(self) -> None:
        """Regular 200 response → BeatmapsetSnapshot with correct fields."""
        provider = _make_provider(api_body=_BEATMAPSET_RESPONSE_BODY)

        result = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert result is not None
        assert result.beatmapset_id == _BEATMAPSET_ID
        assert result.artist == "Camellia"
        assert result.title == "Exit This Earth's Atomosphere"
        assert result.creator == "Realazy"
        assert result.artist_unicode == "かめるりあ"
        assert result.source is BeatmapMetadataSourceName.OFFICIAL
        assert result.verified is True
        assert result.official_status == BeatmapRankStatus.RANKED.value
        assert len(result.beatmaps) == 1

        bm = result.beatmaps[0]
        assert bm.beatmap_id == _BEATMAP_ID
        assert bm.checksum_md5 == _CHECKSUM
        assert bm.mode == "osu"
        assert bm.version == "Another"
        assert bm.bpm == 220.0

    async def test_returns_none_on_404(self) -> None:
        """404 from API returns None (not found, not an error)."""
        provider = _make_provider(api_status=404)

        result = await provider.lookup_by_beatmapset_id(99999)

        assert result is None

    async def test_raises_on_401(self) -> None:
        """401 → BeatmapSourceError(UNAUTHORIZED)."""
        provider = _make_provider(api_status=401)

        with pytest.raises(BeatmapSourceError) as exc_info:
            await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]

        assert exc_info.value.category is BeatmapSourceErrorCategory.UNAUTHORIZED

    async def test_raises_on_429(self) -> None:
        """429 → BeatmapSourceError(RATE_LIMITED)."""
        provider = _make_provider(api_status=429)

        with pytest.raises(BeatmapSourceError) as exc_info:
            await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]

        assert exc_info.value.category is BeatmapSourceErrorCategory.RATE_LIMITED

    @pytest.mark.parametrize("status", [500, 502, 503])
    async def test_raises_on_5xx(self, status: int) -> None:
        """5xx → BeatmapSourceError(TEMPORARY_UNAVAILABLE)."""
        provider = _make_provider(api_status=status)

        with pytest.raises(BeatmapSourceError) as exc_info:
            await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]

        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE

    async def test_raises_on_timeout(self) -> None:
        """httpx.TimeoutException → BeatmapSourceError(TIMEOUT)."""
        provider = _make_provider(api_error=httpx.TimeoutException)

        with pytest.raises(BeatmapSourceError) as exc_info:
            await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]

        assert exc_info.value.category is BeatmapSourceErrorCategory.TIMEOUT

    async def test_raises_on_connection_error(self) -> None:
        """httpx.ConnectError → BeatmapSourceError(TEMPORARY_UNAVAILABLE)."""
        provider = _make_provider(api_error=httpx.ConnectError)

        with pytest.raises(BeatmapSourceError) as exc_info:
            await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]

        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE

    async def test_raises_on_invalid_json(self) -> None:
        """Non-JSON response body → BeatmapSourceError(INVALID_RESPONSE)."""
        handler = _handler_for(api_status=200)
        transport = httpx.MockTransport(handler)
        # Override the handler to return garbage bytes
        client = httpx.AsyncClient(transport=transport)

        def bad_json(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue, reportUnknownArgumentType]
            if _TOKEN_URL in url_str and request.method == "POST":  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
                return httpx.Response(
                    200,
                    content=json.dumps(_TOKEN_RESPONSE_BODY).encode(),
                    request=request,
                )
            return httpx.Response(200, content=b"not valid json {{{", request=request)

        transport = httpx.MockTransport(bad_json)
        client = httpx.AsyncClient(transport=transport)
        provider = OsuApiMetadataProvider(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
        )
        provider._httpx_client = client  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        with pytest.raises(BeatmapSourceError) as exc_info:
            await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]

        assert exc_info.value.category is BeatmapSourceErrorCategory.INVALID_RESPONSE


# ---------------------------------------------------------------------------
# lookup_by_beatmap_id
# ---------------------------------------------------------------------------


class TestLookupByBeatmapId:
    async def test_returns_snapshot_from_beatmap_endpoint(self) -> None:
        """Beatmap endpoint response (nested beatmapset) is correctly unwrapped."""
        provider = _make_provider(api_body=_BEATMAP_RESPONSE_BODY)

        result = await provider.lookup_by_beatmap_id(_BEATMAP_ID)

        assert result is not None
        assert result.beatmapset_id == _BEATMAPSET_ID
        assert result.artist == "Camellia"
        assert len(result.beatmaps) == 1
        assert result.beatmaps[0].beatmap_id == _BEATMAP_ID

    async def test_returns_none_on_404(self) -> None:
        provider = _make_provider(api_status=404)

        result = await provider.lookup_by_beatmap_id(99999)

        assert result is None


# ---------------------------------------------------------------------------
# lookup_by_checksum
# ---------------------------------------------------------------------------


class TestLookupByChecksum:
    async def test_returns_snapshot_from_checksum_lookup(self) -> None:
        """Checksum lookup uses the same beatmap endpoint response shape."""
        provider = _make_provider(api_body=_BEATMAP_RESPONSE_BODY)

        result = await provider.lookup_by_checksum(_CHECKSUM)

        assert result is not None
        assert result.beatmapset_id == _BEATMAPSET_ID

    async def test_returns_none_on_404(self) -> None:
        provider = _make_provider(api_status=404)

        result = await provider.lookup_by_checksum("f" * 32)

        assert result is None


# ---------------------------------------------------------------------------
# OAuth2 token management
# ---------------------------------------------------------------------------


class TestTokenManagement:
    async def test_acquires_token_on_first_call(self) -> None:
        """First API call triggers token acquisition."""
        provider = _make_provider(api_body=_BEATMAPSET_RESPONSE_BODY)

        assert provider._access_token is None  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        assert provider._token_expiry == 0.0  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]

        assert provider._access_token == "tok_deadbeef"  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        assert provider._token_expiry > 0.0  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    async def test_reuses_cached_token(self) -> None:
        """Second call reuses cached token (no new token request)."""
        provider = _make_provider(api_body=_BEATMAPSET_RESPONSE_BODY)

        await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]
        _first_expiry = provider._token_expiry  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        # Make a second call — token should be reused
        await provider.lookup_by_beatmap_id(_BEATMAP_ID)  # pyright: ignore[reportUnusedCallResult]

        assert provider._token_expiry == _first_expiry  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    async def test_refreshes_expired_token(self) -> None:
        """When token is expired, a new one is acquired."""
        provider = _make_provider(api_body=_BEATMAPSET_RESPONSE_BODY, token_count=1)

        await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]
        _old_token = provider._access_token  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        # Force expiry
        provider._token_expiry = time.monotonic() - 1.0  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        provider._access_token = "stale_token"  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]

        assert provider._access_token != _old_token  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        assert provider._access_token == "tok_00000002"  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    async def test_raises_on_token_401(self) -> None:
        """401 from token endpoint → BeatmapSourceError(UNAUTHORIZED)."""
        provider = _make_provider(token_status=401)

        with pytest.raises(BeatmapSourceError) as exc_info:
            await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]

        assert exc_info.value.category is BeatmapSourceErrorCategory.UNAUTHORIZED
        assert exc_info.value.source == "osu_oauth"

    async def test_raises_on_token_error_response(self) -> None:
        """5xx from token endpoint → BeatmapSourceError(TEMPORARY_UNAVAILABLE)."""
        provider = _make_provider(token_status=503)

        with pytest.raises(BeatmapSourceError) as exc_info:
            await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]

        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE
        assert exc_info.value.source == "osu_oauth"

    async def test_raises_on_token_timeout(self) -> None:
        """Timeout on token endpoint → BeatmapSourceError(TIMEOUT)."""
        provider = _make_provider(token_error=httpx.TimeoutException)

        with pytest.raises(BeatmapSourceError) as exc_info:
            await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]

        assert exc_info.value.category is BeatmapSourceErrorCategory.TIMEOUT
        assert exc_info.value.source == "osu_oauth"

    async def test_raises_on_invalid_token_json(self) -> None:
        """Non-JSON token response → BeatmapSourceError(INVALID_RESPONSE)."""
        handler = _handler_for()
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        def bad_token(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue, reportUnknownArgumentType]
            if _TOKEN_URL in url_str and request.method == "POST":  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
                return httpx.Response(200, content=b"not valid json {{{", request=request)
            return httpx.Response(
                200,
                content=json.dumps(_BEATMAPSET_RESPONSE_BODY).encode(),
                request=request,
            )

        transport = httpx.MockTransport(bad_token)
        client = httpx.AsyncClient(transport=transport)
        provider = OsuApiMetadataProvider(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
        )
        provider._httpx_client = client  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

        with pytest.raises(BeatmapSourceError) as exc_info:
            await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)  # pyright: ignore[reportUnusedCallResult]

        assert exc_info.value.category is BeatmapSourceErrorCategory.INVALID_RESPONSE
        assert exc_info.value.source == "osu_oauth"


# ---------------------------------------------------------------------------
# Status mapping integration
# ---------------------------------------------------------------------------


class TestStatusMapping:
    """Verify osu! API status strings are correctly mapped."""

    @pytest.mark.parametrize(
        ("api_status", "expected"),
        [
            ("ranked", BeatmapRankStatus.RANKED),
            ("loved", BeatmapRankStatus.LOVED),
            ("qualified", BeatmapRankStatus.QUALIFIED),
            ("pending", BeatmapRankStatus.PENDING),
            ("wip", BeatmapRankStatus.WIP),
            ("graveyard", BeatmapRankStatus.GRAVEYARD),
        ],
    )
    async def test_status_mapping(self, api_status: str, expected: BeatmapRankStatus) -> None:
        body = dict(_BEATMAPSET_RESPONSE_BODY)
        body["status"] = api_status
        if "beatmaps" in body:
            beatmaps = cast("list[dict[str, object]]", body["beatmaps"])
            for bm in beatmaps:
                bm["status"] = api_status

        provider = _make_provider(api_body=body)

        result = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert result is not None
        assert result.official_status == expected.value
        assert result.beatmaps[0].official_status == expected.value
