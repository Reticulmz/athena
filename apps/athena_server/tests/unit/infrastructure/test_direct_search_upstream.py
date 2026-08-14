"""osu!direct external search upstream adapterの契約を検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

import httpx

from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSourceVerification,
    DirectSearchListing,
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


async def test_cheesegull_provider_uses_ranked_direct_filter_for_ranked_group() -> None:
    """Ranked系stable filterをHinamizawa direct互換のranked queryへ畳む契約を検証する.

    Stable `r=0` はHinamizawa direct仕様と同じrankedのみとして扱うため、`status=1`を
    1回だけ照会することを確認する.

    Returns:
        None: ranked direct query, page上限, more flagを検証して完了する.
    """
    requested_statuses: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """MockTransportでHinamizawa ranked検索responseを返す.

        Args:
            request (httpx.Request): providerが送信したHTTP request.

        Returns:
            httpx.Response: ranked direct互換のCheeseGull型検索結果JSON.
        """
        mock_request = _mock_transport_request(request)
        status = mock_request.url.params["status"]
        requested_statuses.append(status)
        rows = [_cheesegull_row(1000), _cheesegull_row(1001), _cheesegull_row(1002)]
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
                statuses=(BeatmapRankStatus.RANKED,),
                page_size=2,
            )
        )

    assert requested_statuses == ["1"]
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [1000, 1001]
    assert result.has_more is True


async def test_cheesegull_provider_expands_all_status_search() -> None:
    """Stable All filterをHinamizawa v1の明示status検索へ展開する契約を検証する.

    `status`を省略したv1検索がsource側の既定statusに偏っても、Stable `r=4`のAllでは
    v1が公開しているstatusを個別に取得し、Newest順で混在statusを返すことを確認する.

    Returns:
        None: All検索のstatus query列とNewest順の混在結果を検証して完了する.
    """
    requested_statuses: list[str] = []
    rows_by_status = {
        "0": [_cheesegull_row(1000, ranked_status=0, last_update="2026-01-01T00:00:00Z")],
        "1": [_cheesegull_row(1001, ranked_status=1, last_update="2026-01-02T00:00:00Z")],
        "2": [_cheesegull_row(1002, ranked_status=2, last_update="2026-01-03T00:00:00Z")],
        "3": [_cheesegull_row(1003, ranked_status=3, last_update="2026-01-04T00:00:00Z")],
        "4": [_cheesegull_row(1004, ranked_status=4, last_update="2026-01-05T00:00:00Z")],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        """MockTransportでstatus別のHinamizawa検索responseを返す.

        Args:
            request (httpx.Request): providerが送信したHTTP request.

        Returns:
            httpx.Response: status queryに対応するCheeseGull互換検索結果JSON.
        """
        params = _mock_transport_request(request).url.params
        status = params.get("status")
        requested_statuses.append(status or "<missing>")
        fallback_rows = [
            _cheesegull_row(9999, ranked_status=1, last_update="2026-01-06T00:00:00Z")
        ]
        rows = fallback_rows if status is None else rows_by_status.get(status, fallback_rows)
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
                statuses=(),
                listing=DirectSearchListing.NEWEST,
                page_size=3,
            )
        )

    assert requested_statuses == ["0", "1", "2", "3", "4"]
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [1004, 1003, 1002]
    assert [beatmapset.official_status for beatmapset in result.beatmapsets] == [
        BeatmapRankStatus.LOVED,
        BeatmapRankStatus.QUALIFIED,
        BeatmapRankStatus.APPROVED,
    ]
    assert result.has_more is True


async def test_cheesegull_provider_paginates_expanded_all_status_globally() -> None:
    """All status展開後のpageをstatus別offsetではなくglobal順で切り出す契約を検証する.

    Stable `r=4&p=1`では各statusの2件目以降を単純連結するのではなく、要求pageまでの
    status別候補を集めてNewest順に並べ、全status混在結果の2page目を返すことを確認する.

    Returns:
        None: status別request offsetとglobal page結果を検証して完了する.
    """
    requested_pages: list[tuple[str, str]] = []
    rows_by_page = {
        ("0", "0"): [
            _cheesegull_row(1000, ranked_status=0, last_update="2026-01-06T00:00:00Z"),
            _cheesegull_row(1002, ranked_status=0, last_update="2026-01-04T00:00:00Z"),
        ],
        ("0", "2"): [_cheesegull_row(1004, ranked_status=0, last_update="2026-01-02T00:00:00Z")],
        ("1", "0"): [
            _cheesegull_row(1001, ranked_status=1, last_update="2026-01-05T00:00:00Z"),
            _cheesegull_row(1003, ranked_status=1, last_update="2026-01-03T00:00:00Z"),
        ],
        ("1", "2"): [_cheesegull_row(1005, ranked_status=1, last_update="2026-01-01T00:00:00Z")],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        """MockTransportでstatusとoffsetに対応する検索pageを返す.

        Args:
            request (httpx.Request): providerが送信したHTTP request.

        Returns:
            httpx.Response: 指定status/pageのCheeseGull互換検索結果JSON.
        """
        params = _mock_transport_request(request).url.params
        page_key = (params["status"], params["offset"])
        requested_pages.append(page_key)
        assert params["amount"] == "2"
        return httpx.Response(200, json=rows_by_page.get(page_key, []))

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
                statuses=(),
                listing=DirectSearchListing.NEWEST,
                page=1,
                page_size=2,
            )
        )

    assert requested_pages == [
        ("0", "0"),
        ("0", "2"),
        ("1", "0"),
        ("1", "2"),
        ("2", "0"),
        ("2", "2"),
        ("3", "0"),
        ("3", "2"),
        ("4", "0"),
        ("4", "2"),
    ]
    assert [beatmapset.id for beatmapset in result.beatmapsets] == [1002, 1003]
    assert result.has_more is True


async def test_cheesegull_provider_uses_graveyard_status_query() -> None:
    """Graveyard stable filterをHinamizawa JSON検索の`status=-2`へ変換する契約を検証する.

    Returns:
        None: Graveyard検索のstatus queryとdomain変換結果を検証して完了する.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """MockTransportでGraveyard検索requestとJSON responseを返す.

        Args:
            request (httpx.Request): providerが送信したHTTP request.

        Returns:
            httpx.Response: GraveyardのCheeseGull互換検索結果JSON.
        """
        mock_request = _mock_transport_request(request)
        assert mock_request.url.params["status"] == "-2"
        return httpx.Response(200, json=[_cheesegull_row(1000, ranked_status=-2)])

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
                statuses=(BeatmapRankStatus.GRAVEYARD,),
            )
        )

    assert result.beatmapsets[0].official_status is BeatmapRankStatus.GRAVEYARD


async def test_cheesegull_provider_translates_special_listings_to_hinamizawa_sort() -> None:
    """Stable directのquick queryをHinamizawa JSON検索のsortへ変換する契約を検証する.

    `Newest`, `Top Rated`, `Most Played` はliteral text検索ではなく、空queryとsort指定として
    `/api/v1/hinai/search` へ渡すことを確認する.

    Returns:
        None: special listingごとのquery, status, mode, amount, offset, sortを検証する.
    """
    observed_params: list[tuple[str, str, str, str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """MockTransportでspecial listing検索requestを記録して空JSON responseを返す.

        Args:
            request (httpx.Request): providerが送信したHTTP request.

        Returns:
            httpx.Response: 空のCheeseGull互換検索結果JSON.
        """
        params = _mock_transport_request(request).url.params
        observed_params.append(
            (
                params["query"],
                params["mode"],
                params["status"],
                params["amount"],
                params["offset"],
                params["sort"],
            )
        )
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = CheeseGullDirectSearchUpstreamProvider(
            http_client=BeatmapHttpClient(client),
            search_url="https://mirror.hinamizawa.ai/api/v1/hinai/search",
            source_label="hinamizawa",
        )

        for listing in (
            DirectSearchListing.NEWEST,
            DirectSearchListing.TOP_RATED,
            DirectSearchListing.MOST_PLAYED,
        ):
            _ = await provider.search(
                DirectSearchRequest(
                    authenticated_user_id=1,
                    query_text=listing.value,
                    statuses=(BeatmapRankStatus.LOVED,),
                    mode=BeatmapMode.OSU,
                    page=1,
                    listing=listing,
                )
            )

    assert observed_params == [
        ("", "0", "4", "100", "100", "ranked_desc"),
        ("", "0", "4", "100", "100", "favourites_desc"),
        ("", "0", "4", "100", "100", "plays_desc"),
    ]


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


def _cheesegull_row(
    beatmapset_id: int,
    *,
    ranked_status: int = 1,
    last_update: str = "2024-01-02T03:04:05Z",
) -> dict[str, object]:
    """CheeseGull互換のbeatmapset検索rowを作る.

    Args:
        beatmapset_id (int): rowへ設定するbeatmapset ID.
        ranked_status (int): `RankedStatus` fieldへ設定するCheeseGull互換status値.
        last_update (str): `LastUpdate` fieldへ設定する更新日時文字列.

    Returns:
        dict[str, object]: Hinamizawa JSON検索と同型の最小row.
    """
    return {
        "SetID": beatmapset_id,
        "Artist": "Camellia",
        "Title": f"Title {beatmapset_id}",
        "Creator": "Mapper",
        "RankedStatus": ranked_status,
        "LastUpdate": last_update,
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
