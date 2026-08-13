"""osu!direct external search upstream adapterの契約を検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

import httpx

from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSourceVerification,
    DirectSearchRequest,
    DirectSearchUpstreamResult,
)
from osu_server.infrastructure.beatmaps.direct_search_upstream import (
    CheeseGullDirectSearchUpstreamProvider,
    NerinyanDirectSearchUpstreamProvider,
    SequentialDirectSearchUpstreamProvider,
)
from osu_server.infrastructure.http.beatmap_http_client import BeatmapHttpClient

if TYPE_CHECKING:
    from collections.abc import Mapping


class _MockTransportUrl(Protocol):
    """MockTransport request URLからtestが読む最小interfaceを表す."""

    @property
    def path(self) -> str:
        """URL pathを返す.

        Returns:
            str: request URLのpath.
        """
        ...

    @property
    def params(self) -> Mapping[str, str]:
        """Query parameter mappingを返す.

        Returns:
            Mapping[str, str]: request URLのquery parameter.
        """
        ...


class _MockTransportRequest(Protocol):
    """MockTransport requestからtestが読む最小interfaceを表す."""

    @property
    def url(self) -> _MockTransportUrl:
        """Request URLを返す.

        Returns:
            _MockTransportUrl: pathとquery parameterを参照できるURL object.
        """
        ...

    @property
    def headers(self) -> Mapping[str, str]:
        """Request header mappingを返す.

        Returns:
            Mapping[str, str]: request header.
        """
        ...


def _mock_transport_request(request: httpx.Request) -> _MockTransportRequest:
    """httpx.RequestをMockTransport検証用Protocolへnarrowする.

    Args:
        request (httpx.Request): MockTransport handlerが受け取ったrequest.

    Returns:
        _MockTransportRequest: testが参照するURLとheadersだけを持つview.
    """
    return cast("_MockTransportRequest", cast("object", request))


async def test_cheesegull_provider_maps_hinamizawa_json_search_results() -> None:
    """Hinamizawa JSON検索のCheeseGull方言をdomain beatmapsetへ変換する契約を検証する.

    Returns:
        None: request queryと変換済みmetadata候補を検証して完了する.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """MockTransportでHinamizawa検索requestとJSON responseを再現する.

        Args:
            request (httpx.Request): providerが送信したHTTP request.

        Returns:
            httpx.Response: CheeseGull互換の検索結果JSON.
        """
        mock_request = _mock_transport_request(request)
        assert mock_request.url.path == "/api/v1/hinai/search"
        assert mock_request.headers["User-Agent"] == "Athena osu!direct search"
        assert mock_request.url.params["query"] == "camellia"
        assert mock_request.url.params["mode"] == "0"
        assert mock_request.url.params["status"] == "1"
        assert mock_request.url.params["amount"] == "2"
        assert mock_request.url.params["offset"] == "2"
        return httpx.Response(
            200,
            json=[
                _cheesegull_row(1000),
                _cheesegull_row(1001),
                _cheesegull_row(1002),
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = CheeseGullDirectSearchUpstreamProvider(
            http_client=BeatmapHttpClient(client),
            search_url="https://mirror.hinamizawa.ai/api/v1/hinai/search",
            source_label="hinamizawa",
            headers={"User-Agent": "Athena osu!direct search"},
        )

        result = await provider.search(
            DirectSearchRequest(
                authenticated_user_id=1,
                query_text="camellia",
                statuses=(BeatmapRankStatus.RANKED,),
                mode=BeatmapMode.OSU,
                page=1,
                page_size=2,
            )
        )

    assert result.has_more is True
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [1000, 1001]
    assert result.beatmapsets[0].artist == "Camellia"
    assert result.beatmapsets[0].official_status is BeatmapRankStatus.RANKED
    assert result.beatmapsets[0].official_status_source is BeatmapMetadataSource.MIRROR
    assert result.beatmapsets[0].official_status_verified is BeatmapSourceVerification.UNVERIFIED
    assert result.beatmapsets[0].beatmaps[0].mode is BeatmapMode.OSU


async def test_cheesegull_provider_splits_multi_status_search() -> None:
    """複合status検索をCheeseGullが扱える単一status queryへ分解する契約を検証する.

    Stable `r=0` はrankedとapprovedを同時に要求するが, CheeseGull互換JSON検索は単一status
    queryだけを受けるため, status別に取得してBeatmapSet IDで重複排除することを確認する.

    Returns:
        None: status別request, page上限, more flagを検証して完了する.
    """
    requested_statuses: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """MockTransportでstatus別CheeseGull検索responseを返す.

        Args:
            request (httpx.Request): providerが送信したHTTP request.

        Returns:
            httpx.Response: statusごとのCheeseGull互換検索結果JSON.
        """
        mock_request = _mock_transport_request(request)
        status = mock_request.url.params["status"]
        requested_statuses.append(status)
        rows = (
            [_cheesegull_row(1000), _cheesegull_row(1001)]
            if status == "1"
            else [_cheesegull_row(1001), _cheesegull_row(1002)]
        )
        return httpx.Response(200, json=rows)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = CheeseGullDirectSearchUpstreamProvider(
            http_client=BeatmapHttpClient(client),
            search_url="https://mirror.hinamizawa.ai/api/v1/hinai/search",
            source_label="hinamizawa",
        )

        result = await provider.search(
            DirectSearchRequest(
                authenticated_user_id=1,
                query_text="",
                statuses=(BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED),
                page_size=2,
            )
        )

    assert requested_statuses == ["1", "2"]
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [1000, 1001]
    assert result.has_more is True


async def test_nerinyan_provider_maps_v2_search_results() -> None:
    """Nerinyan v2検索のosu API v2風JSONをdomain beatmapsetへ変換する契約を検証する.

    Returns:
        None: Nerinyan query parameterと変換済みmetadata候補を検証して完了する.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """MockTransportでNerinyan検索requestとJSON responseを再現する.

        Args:
            request (httpx.Request): providerが送信したHTTP request.

        Returns:
            httpx.Response: osu API v2風の検索結果JSON.
        """
        mock_request = _mock_transport_request(request)
        assert mock_request.url.path == "/v2/search"
        assert mock_request.url.params["q"] == "lapix"
        assert mock_request.url.params["m"] == "3"
        assert mock_request.url.params["s"] == "loved"
        assert mock_request.url.params["p"] == "1"
        assert mock_request.url.params["ps"] == "1"
        return httpx.Response(
            200,
            json={
                "beatmapsets": [_v2_beatmapset(2000), _v2_beatmapset(2001)],
                "cursor": {"approved_date": "2024-01-01T00:00:00Z"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = NerinyanDirectSearchUpstreamProvider(
            http_client=BeatmapHttpClient(client),
            search_url="https://api.nerinyan.moe/v2/search",
        )

        result = await provider.search(
            DirectSearchRequest(
                authenticated_user_id=1,
                query_text="lapix",
                statuses=(BeatmapRankStatus.LOVED,),
                mode=BeatmapMode.MANIA,
                page=0,
                page_size=1,
            )
        )

    assert result.has_more is True
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [2000]
    assert result.beatmapsets[0].official_status is BeatmapRankStatus.LOVED
    assert result.beatmapsets[0].beatmaps[0].mode is BeatmapMode.MANIA


async def test_sequential_provider_uses_next_provider_after_failure() -> None:
    """Sequential providerが失敗した上流を飛ばして次の候補を使う契約を検証する.

    Returns:
        None: 失敗provider後に成功providerの結果を返すことを検証して完了する.
    """
    request = DirectSearchRequest(authenticated_user_id=1, query_text="camellia", page_size=1)
    expected = DirectSearchUpstreamResult(beatmapsets=(), has_more=False)
    succeeding = _SucceedingUpstreamProvider(expected)
    provider = SequentialDirectSearchUpstreamProvider((_FailingUpstreamProvider(), succeeding))

    result = await provider.search(request)

    assert result == expected
    assert succeeding.requests == [request]


class _FailingUpstreamProvider:
    """常に失敗するupstream provider test doubleを提供する."""

    async def search(self, request: DirectSearchRequest) -> DirectSearchUpstreamResult:
        """受け取ったrequestに関係なくRuntimeErrorを送出する.

        Args:
            request (DirectSearchRequest): 呼び出し側が渡した検索条件.

        Raises:
            RuntimeError: fallback動作を検証するため常に送出する.
        """
        _ = request
        raise RuntimeError("upstream failed")


class _SucceedingUpstreamProvider:
    """固定結果を返しrequestを記録するupstream provider test doubleを提供する.

    Attributes:
        result (DirectSearchUpstreamResult): searchで返す固定結果.
        requests (list[DirectSearchRequest]): searchへ渡されたrequestの記録.
    """

    result: DirectSearchUpstreamResult
    requests: list[DirectSearchRequest]

    def __init__(self, result: DirectSearchUpstreamResult) -> None:
        """返却する固定結果を保持する.

        Args:
            result (DirectSearchUpstreamResult): searchで返す結果.
        """
        self.result = result
        self.requests = []

    async def search(self, request: DirectSearchRequest) -> DirectSearchUpstreamResult:
        """Requestを記録して固定結果を返す.

        Args:
            request (DirectSearchRequest): 呼び出し側が渡した検索条件.

        Returns:
            DirectSearchUpstreamResult: 初期化時に渡された固定結果.
        """
        self.requests.append(request)
        return self.result


def _cheesegull_row(beatmapset_id: int) -> dict[str, object]:
    """CheeseGull互換のbeatmapset検索rowを作る.

    Args:
        beatmapset_id (int): rowへ設定するbeatmapset ID.

    Returns:
        dict[str, object]: Hinamizawa JSON検索と同型の最小row.
    """
    return {
        "SetID": beatmapset_id,
        "Artist": "Camellia",
        "Title": f"Title {beatmapset_id}",
        "Creator": "Mapper",
        "RankedStatus": 1,
        "LastUpdate": "2024-01-02T03:04:05Z",
        "Source": "album",
        "Tags": "electronic",
        "ChildrenBeatmaps": [
            {
                "BeatmapID": beatmapset_id * 10,
                "FileMD5": f"{beatmapset_id:032x}",
                "Mode": 0,
                "DiffName": "Normal",
                "TotalLength": 120,
                "HitLength": 100,
                "MaxCombo": 500,
                "BPM": 180,
                "CS": 4,
                "OD": 8,
                "AR": 9,
                "HP": 6,
                "DifficultyRating": 5.0,
            }
        ],
    }


def _v2_beatmapset(beatmapset_id: int) -> dict[str, object]:
    """Osu API v2風のbeatmapset検索rowを作る.

    Args:
        beatmapset_id (int): rowへ設定するbeatmapset ID.

    Returns:
        dict[str, object]: Nerinyan v2検索と同型の最小row.
    """
    return {
        "id": beatmapset_id,
        "artist": "lapix",
        "title": f"Title {beatmapset_id}",
        "creator": "Mapper",
        "status": "loved",
        "source": "album",
        "tags": "electronic",
        "beatmaps": [
            {
                "id": beatmapset_id * 10,
                "beatmapset_id": beatmapset_id,
                "checksum": f"{beatmapset_id:032x}",
                "mode": "mania",
                "version": "Another",
                "status": "loved",
                "total_length": 120,
                "hit_length": 100,
                "max_combo": 500,
                "bpm": 180,
                "cs": 4,
                "accuracy": 8,
                "ar": 9,
                "drain": 6,
                "difficulty_rating": 5.0,
            }
        ],
    }
