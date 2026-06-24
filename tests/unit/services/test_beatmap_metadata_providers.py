"""Tests for OsuApiMetadataProviderService — osu! API v2 integration.

Uses httpx.MockTransport for deterministic HTTP simulation.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol, cast

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
    BeatmapSourceVerification,
)
from osu_server.infrastructure.http.beatmap_http_client import BeatmapHttpClient
from osu_server.services.queries.beatmaps.mirror import OsuApiMetadataProviderService


class _RequestHeaders(Protocol):
    headers: Mapping[str, str]


class _MockTransportRequest(Protocol):
    @property
    def url(self) -> object: ...

    @property
    def method(self) -> str: ...


def _request_url_and_method(request: httpx.Request) -> tuple[str, str]:
    mock_request = cast("_MockTransportRequest", cast("object", request))
    return str(mock_request.url), mock_request.method


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


class _MetadataProviderMockHandler:
    """Build a httpx.MockTransport handler function.

    Routes POST to _TOKEN_URL → token response, GET to _BASE_URL/* → API response.
    When *token_count* > 0, each token request returns ``tok_<N>`` with incrementing N.
    """

    _api_status: int
    _api_body: Mapping[str, object] | None
    _api_error: type[Exception] | None
    _token_status: int
    _token_body: Mapping[str, object] | None
    _token_error: type[Exception] | None
    _token_count: int
    _token_expires_in: int
    token_request_count: int
    authorization_headers: list[str | None]

    def __init__(
        self,
        *,
        api_status: int,
        api_body: Mapping[str, object] | None,
        api_error: type[Exception] | None,
        token_status: int,
        token_body: Mapping[str, object] | None,
        token_error: type[Exception] | None,
        token_count: int,
        token_expires_in: int,
    ) -> None:
        self._api_status = api_status
        self._api_body = api_body
        self._api_error = api_error
        self._token_status = token_status
        self._token_body = token_body
        self._token_error = token_error
        self._token_count = token_count
        self._token_expires_in = token_expires_in
        self.token_request_count = 0
        self.authorization_headers = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url_str, method = _request_url_and_method(request)

        # -- Token endpoint (POST) --------------------------------------------
        if _TOKEN_URL in url_str and method == "POST":
            if self._token_error is not None:
                raise self._token_error("mock token error")
            self.token_request_count += 1
            if self._token_count > 0:
                # Return incrementing token values
                body = {
                    "access_token": f"tok_{self.token_request_count:08x}",
                    "expires_in": self._token_expires_in,
                }
            else:
                body = self._token_body if self._token_body is not None else _TOKEN_RESPONSE_BODY
            return httpx.Response(
                self._token_status,
                content=json.dumps(body).encode(),
                request=request,
            )

        # -- API endpoints (GET) ----------------------------------------------
        request_headers = cast("_RequestHeaders", cast("object", request))
        self.authorization_headers.append(request_headers.headers.get("Authorization"))
        if self._api_error is not None:
            raise self._api_error("mock api error")
        body = self._api_body if self._api_body is not None else _BEATMAPSET_RESPONSE_BODY
        return httpx.Response(
            self._api_status,
            content=json.dumps(body).encode(),
            request=request,
        )


def _handler_for(
    *,
    api_status: int = 200,
    api_body: Mapping[str, object] | None = None,
    api_error: type[Exception] | None = None,
    token_status: int = 200,
    token_body: Mapping[str, object] | None = None,
    token_error: type[Exception] | None = None,
    token_count: int = 0,
    token_expires_in: int = 3600,
) -> _MetadataProviderMockHandler:
    return _MetadataProviderMockHandler(
        api_status=api_status,
        api_body=api_body,
        api_error=api_error,
        token_status=token_status,
        token_body=token_body,
        token_error=token_error,
        token_count=token_count,
        token_expires_in=token_expires_in,
    )


def _make_provider(
    *,
    token_status: int = 200,
    token_body: Mapping[str, object] | None = None,
    api_status: int = 200,
    api_body: Mapping[str, object] | None = None,
    api_error: type[Exception] | None = None,
    token_error: type[Exception] | None = None,
    token_count: int = 0,
) -> OsuApiMetadataProviderService:
    """Create an OsuApiMetadataProviderService backed by a MockTransport."""
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
    http_client = BeatmapHttpClient(client=client)
    return OsuApiMetadataProviderService(
        client_id=_CLIENT_ID,
        client_secret=_CLIENT_SECRET,
        http_client=http_client,
    )


def _make_provider_with_handler(
    *,
    token_count: int = 0,
    token_expires_in: int = 3600,
) -> tuple[OsuApiMetadataProviderService, _MetadataProviderMockHandler]:
    handler = _handler_for(
        api_body=_BEATMAPSET_RESPONSE_BODY,
        token_count=token_count,
        token_expires_in=token_expires_in,
    )
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    http_client = BeatmapHttpClient(client=client)
    return (
        OsuApiMetadataProviderService(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            http_client=http_client,
        ),
        handler,
    )


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
        assert result.source is BeatmapMetadataSource.OFFICIAL
        assert result.verified is BeatmapSourceVerification.VERIFIED
        assert result.official_status is BeatmapRankStatus.RANKED
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
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.UNAUTHORIZED

    async def test_raises_on_429(self) -> None:
        """429 → BeatmapSourceError(RATE_LIMITED)."""
        provider = _make_provider(api_status=429)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.RATE_LIMITED

    @pytest.mark.parametrize("status", [500, 502, 503])
    async def test_raises_on_5xx(self, status: int) -> None:
        """5xx → BeatmapSourceError(TEMPORARY_UNAVAILABLE)."""
        provider = _make_provider(api_status=status)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE

    async def test_raises_on_timeout(self) -> None:
        """httpx.TimeoutException → BeatmapSourceError(TIMEOUT)."""
        provider = _make_provider(api_error=httpx.TimeoutException)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.TIMEOUT

    async def test_raises_on_connection_error(self) -> None:
        """httpx.ConnectError → BeatmapSourceError(TEMPORARY_UNAVAILABLE)."""
        provider = _make_provider(api_error=httpx.ConnectError)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE

    async def test_raises_on_invalid_json(self) -> None:
        """Non-JSON response body → BeatmapSourceError(INVALID_RESPONSE)."""

        def bad_json(request: httpx.Request) -> httpx.Response:
            url_str, method = _request_url_and_method(request)
            if _TOKEN_URL in url_str and method == "POST":
                return httpx.Response(
                    200,
                    content=json.dumps(_TOKEN_RESPONSE_BODY).encode(),
                    request=request,
                )
            return httpx.Response(200, content=b"not valid json {{{", request=request)

        transport = httpx.MockTransport(bad_json)
        client = httpx.AsyncClient(transport=transport)
        http_client = BeatmapHttpClient(client=client)
        provider = OsuApiMetadataProviderService(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            http_client=http_client,
        )

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

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
        provider, handler = _make_provider_with_handler()

        assert handler.token_request_count == 0

        _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert handler.token_request_count == 1
        assert handler.authorization_headers == ["Bearer tok_deadbeef"]

    async def test_reuses_cached_token(self) -> None:
        """Second call reuses cached token (no new token request)."""
        provider, handler = _make_provider_with_handler()

        _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        # Make a second call — token should be reused
        _ = await provider.lookup_by_beatmap_id(_BEATMAP_ID)

        assert handler.token_request_count == 1
        assert handler.authorization_headers == [
            "Bearer tok_deadbeef",
            "Bearer tok_deadbeef",
        ]

    async def test_refreshes_expired_token(self) -> None:
        """When token is expired, a new one is acquired."""
        provider, handler = _make_provider_with_handler(
            token_count=1,
            token_expires_in=1,
        )

        _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)
        _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert handler.token_request_count == 2
        assert handler.authorization_headers == [
            "Bearer tok_00000001",
            "Bearer tok_00000002",
        ]

    async def test_raises_on_token_401(self) -> None:
        """401 from token endpoint → BeatmapSourceError(UNAUTHORIZED)."""
        provider = _make_provider(token_status=401)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.UNAUTHORIZED
        assert exc_info.value.source == "osu_oauth"

    async def test_raises_on_token_error_response(self) -> None:
        """5xx from token endpoint → BeatmapSourceError(TEMPORARY_UNAVAILABLE)."""
        provider = _make_provider(token_status=503)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE
        assert exc_info.value.source == "osu_oauth"

    async def test_raises_on_token_timeout(self) -> None:
        """Timeout on token endpoint → BeatmapSourceError(TIMEOUT)."""
        provider = _make_provider(token_error=httpx.TimeoutException)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.TIMEOUT
        assert exc_info.value.source == "osu_oauth"

    async def test_raises_on_invalid_token_json(self) -> None:
        """Non-JSON token response → BeatmapSourceError(INVALID_RESPONSE)."""
        handler = _handler_for()
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        def bad_token(request: httpx.Request) -> httpx.Response:
            url_str, method = _request_url_and_method(request)
            if _TOKEN_URL in url_str and method == "POST":
                return httpx.Response(200, content=b"not valid json {{{", request=request)
            return httpx.Response(
                200,
                content=json.dumps(_BEATMAPSET_RESPONSE_BODY).encode(),
                request=request,
            )

        transport = httpx.MockTransport(bad_token)
        client = httpx.AsyncClient(transport=transport)
        http_client = BeatmapHttpClient(client=client)
        provider = OsuApiMetadataProviderService(
            client_id=_CLIENT_ID,
            client_secret=_CLIENT_SECRET,
            http_client=http_client,
        )

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

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
        assert result.official_status is expected
        assert result.beatmaps[0].official_status is expected
