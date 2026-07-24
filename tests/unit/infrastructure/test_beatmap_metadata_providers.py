"""公式osu! API metadata providerのHTTP integration契約を検証するmodule."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol, cast

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping

from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
    BeatmapSourceVerification,
)
from osu_server.infrastructure.beatmaps import OsuApiMetadataProviderService
from osu_server.infrastructure.http.beatmap_http_client import BeatmapHttpClient


class _RequestHeaders(Protocol):
    """MockTransport requestのheaderを参照する最小Protocol.

    Attributes:
        headers (Mapping[str, str]): MockTransport requestから参照するHTTP header mapping.
    """

    headers: Mapping[str, str]


class _MockTransportRequest(Protocol):
    """MockTransport requestのURLとHTTP methodを参照する最小Protocol."""

    @property
    def url(self) -> object:
        """MockTransport requestのURL objectを公開するproperty.

        Returns:
            object: MockTransport requestから公開するURL object.
        """
        ...

    @property
    def method(self) -> str:
        """MockTransport requestのHTTP methodを公開するproperty.

        Returns:
            str: MockTransport requestから公開するHTTP method.
        """
        ...


def _request_url_and_method(request: httpx.Request) -> tuple[str, str]:
    """Httpx requestからURL文字列とHTTP methodを抽出する.

    Args:
        request (httpx.Request): MockTransport handlerへ渡されるHTTP request.

    Returns:
        tuple[str, str]: request URL文字列とHTTP methodの組.
    """
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
    """OAuth tokenとmetadata endpointの結果を決定的に再現するMockTransport handler.

    Attributes:
        _api_status (int): metadata endpointが返すHTTP status.
        _api_body (Mapping[str, object] | None): metadata endpoint用のJSON body.
        _api_error (type[Exception] | None): metadata request時に送出するexception typeまたはNone.
        _token_status (int): OAuth token endpointが返すHTTP status.
        _token_body (Mapping[str, object] | None): OAuth token endpoint用のJSON body.
        _token_error (type[Exception] | None): OAuth token requestで送出するexception type.
        _token_count (int): incrementするtoken値を返すtoken request回数.
        _token_expires_in (int): 生成tokenの有効期間を表す秒数.
        token_request_count (int): 受信したOAuth token requestの累計件数.
        authorization_headers (list[str | None]): metadata requestで記録するAuthorization header値.
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
        """tokenとAPI responseの設定および観測stateを初期化する.

        Args:
            api_status (int): testが操作するAPI status値.
            api_body (Mapping[str, object] | None): mock API endpointが返すJSON body.
            api_error (type[Exception] | None): API request時に送出するexception type.
            token_status (int): token endpointが返すHTTP status.
            token_body (Mapping[str, object] | None): token endpointが返すJSON body.
            token_error (type[Exception] | None): token request時に送出するexception type.
            token_count (int): requestごとにincrementするtoken値を返す回数.
            token_expires_in (int): 取得tokenの有効期間を表す秒数.
        """
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
        """Token requestまたはmetadata requestを設定済みresponseへ振り分ける.

        Args:
            request (httpx.Request): MockTransport handlerへ渡されるHTTP request.

        Returns:
            httpx.Response: mock handlerがrequestへ返すHTTP response.

        Raises:
            Exception: 設定済みtoken_errorまたはapi_errorがrequest処理時に存在する場合.
        """
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
    """指定したOAuthとmetadata response条件を持つmock handlerを構築する.

    Args:
        api_status (int): testが操作するAPI status値.
        api_body (Mapping[str, object] | None): mock API endpointが返すJSON body.
        api_error (type[Exception] | None): API request時に送出するexception type.
        token_status (int): token endpointが返すHTTP status.
        token_body (Mapping[str, object] | None): token endpointが返すJSON body.
        token_error (type[Exception] | None): token request時に送出するexception type.
        token_count (int): requestごとにincrementするtoken値を返す回数.
        token_expires_in (int): 取得tokenの有効期間を表す秒数.

    Returns:
        _MetadataProviderMockHandler: 指定したOAuthとAPI条件を持つMockTransport handler.
    """
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
    """指定したmock response条件で公式metadata providerを構築する.

    Args:
        token_status (int): token endpointが返すHTTP status.
        token_body (Mapping[str, object] | None): token endpointが返すJSON body.
        api_status (int): testが操作するAPI status値.
        api_body (Mapping[str, object] | None): mock API endpointが返すJSON body.
        api_error (type[Exception] | None): API request時に送出するexception type.
        token_error (type[Exception] | None): token request時に送出するexception type.
        token_count (int): requestごとにincrementするtoken値を返す回数.

    Returns:
        OsuApiMetadataProviderService: MockTransportを注入した公式metadata provider.
    """
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
    """Token request履歴を観測できるmock handler付きproviderを構築する.

    Args:
        token_count (int): requestごとにincrementするtoken値を返す回数.
        token_expires_in (int): 取得tokenの有効期間を表す秒数.

    Returns:
        tuple[OsuApiMetadataProviderService, _MetadataProviderMockHandler]:
            公式metadata providerとtoken request履歴を観測するhandlerの組.
    """
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
    """beatmapset IDによる公式metadata lookupの成功とerror mappingを検証するtest群."""

    async def test_returns_snapshot_on_success(self) -> None:
        """200 responseをlookupし公式snapshotの主要metadata fieldを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
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
        assert bm.mode is BeatmapMode.OSU
        assert bm.version == "Another"
        assert bm.bpm == 220.0

    async def test_returns_none_on_404(self) -> None:
        """404 responseを返すmockで未知beatmapsetをlookupしたときNoneを返すことを確認する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(api_status=404)

        result = await provider.lookup_by_beatmapset_id(99999)

        assert result is None

    async def test_raises_on_401(self) -> None:
        """401 responseをlookupしUNAUTHORIZED categoryのerrorを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(api_status=401)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.UNAUTHORIZED

    async def test_raises_on_429(self) -> None:
        """429 responseをlookupしRATE_LIMITED categoryのerrorを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(api_status=429)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.RATE_LIMITED

    @pytest.mark.parametrize("status", [500, 502, 503])
    async def test_raises_on_5xx(self, status: int) -> None:
        """各5xx responseをlookupしTEMPORARY_UNAVAILABLE errorへの変換を検証する.

        Args:
            status (int): parametrized mock HTTP status.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(api_status=status)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE

    async def test_raises_on_timeout(self) -> None:
        """TimeoutExceptionを送出するmockでlookupしたときTIMEOUT categoryへ変換することを確認する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(api_error=httpx.TimeoutException)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.TIMEOUT

    async def test_raises_on_connection_error(self) -> None:
        """ConnectError時のlookupがTEMPORARY_UNAVAILABLE errorになることを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(api_error=httpx.ConnectError)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE

    async def test_raises_on_invalid_json(self) -> None:
        """不正JSONを返すAPI lookupがINVALID_RESPONSE errorになることを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """

        def bad_json(request: httpx.Request) -> httpx.Response:
            """Token endpointへ正常JSONを返しAPIへ不正JSONを返すhandlerを構築する.

            Args:
                request (httpx.Request): MockTransport handlerへ渡されるHTTP request.

            Returns:
                httpx.Response: mock handlerがrequestへ返すHTTP response.
            """
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
    """beatmap IDによる公式metadata lookupのresponse正規化を検証するtest群."""

    async def test_returns_snapshot_from_beatmap_endpoint(self) -> None:
        """Nested beatmapsetを含むresponseをsnapshotへ正規化することを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(api_body=_BEATMAP_RESPONSE_BODY)

        result = await provider.lookup_by_beatmap_id(_BEATMAP_ID)

        assert result is not None
        assert result.beatmapset_id == _BEATMAPSET_ID
        assert result.artist == "Camellia"
        assert len(result.beatmaps) == 1
        assert result.beatmaps[0].beatmap_id == _BEATMAP_ID

    async def test_returns_none_on_404(self) -> None:
        """404 responseを返すmockで未知beatmap IDをlookupしたときNoneを返すことを確認する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(api_status=404)

        result = await provider.lookup_by_beatmap_id(99999)

        assert result is None


# ---------------------------------------------------------------------------
# lookup_by_checksum
# ---------------------------------------------------------------------------


class TestLookupByChecksum:
    """checksumによる公式metadata lookupのresponse契約を検証するtest群."""

    async def test_returns_snapshot_from_checksum_lookup(self) -> None:
        """Beatmap responseを返すmockでchecksum lookupしたときsnapshotを返すことを確認する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(api_body=_BEATMAP_RESPONSE_BODY)

        result = await provider.lookup_by_checksum(_CHECKSUM)

        assert result is not None
        assert result.beatmapset_id == _BEATMAPSET_ID

    async def test_returns_none_on_404(self) -> None:
        """404 responseを返すmockで未知checksumをlookupしたときNoneを返すことを確認する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(api_status=404)

        result = await provider.lookup_by_checksum("f" * 32)

        assert result is None


# ---------------------------------------------------------------------------
# OAuth2 token management
# ---------------------------------------------------------------------------


class TestTokenManagement:
    """OAuth tokenの取得再利用期限切れ更新とerror mappingを検証するtest群."""

    async def test_acquires_token_on_first_call(self) -> None:
        """初回lookupでtoken requestが1回となりBearer headerを送ることを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider, handler = _make_provider_with_handler()

        assert handler.token_request_count == 0

        _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert handler.token_request_count == 1
        assert handler.authorization_headers == ["Bearer tok_deadbeef"]

    async def test_reuses_cached_token(self) -> None:
        """連続lookupでcached tokenを再利用しtoken requestを増やさないことを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
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
        """期限切れtokenで連続lookupし新しいBearer tokenを取得することを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
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
        """Token endpointの401 responseをUNAUTHORIZED errorへ変換することを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(token_status=401)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.UNAUTHORIZED
        assert exc_info.value.source == "osu_oauth"

    async def test_raises_on_token_error_response(self) -> None:
        """Token endpointの5xx responseをTEMPORARY_UNAVAILABLE errorへ変換することを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(token_status=503)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE
        assert exc_info.value.source == "osu_oauth"

    async def test_raises_on_token_timeout(self) -> None:
        """Token endpointのTimeoutExceptionをTIMEOUT errorへ変換することを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        provider = _make_provider(token_error=httpx.TimeoutException)

        with pytest.raises(BeatmapSourceError) as exc_info:
            _ = await provider.lookup_by_beatmapset_id(_BEATMAPSET_ID)

        assert exc_info.value.category is BeatmapSourceErrorCategory.TIMEOUT
        assert exc_info.value.source == "osu_oauth"

    async def test_raises_on_invalid_token_json(self) -> None:
        """Token endpointの不正JSONをINVALID_RESPONSE errorへ変換することを検証する.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
        handler = _handler_for()
        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)

        def bad_token(request: httpx.Request) -> httpx.Response:
            """Token endpointへ不正JSONを返しAPIへ正常JSONを返すhandlerを構築する.

            Args:
                request (httpx.Request): MockTransport handlerへ渡されるHTTP request.

            Returns:
                httpx.Response: mock handlerがrequestへ返すHTTP response.
            """
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
    """公式API status文字列をdomain rank statusへ変換する契約を検証するtest群."""

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
        """各API statusでlookupしsetとbeatmapが同じrank statusになることを検証する.

        Args:
            api_status (str): testが操作するAPI status値.
            expected (BeatmapRankStatus): domainへ変換されるexpected rank status.

        Returns:
            None: 検証またはtest helperの処理を完了し値を返さない.
        """
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
