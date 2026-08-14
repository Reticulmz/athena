"""osu!direct検索を外部mirrorのJSON方言へ接続するadapterを提供する."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, cast
from urllib.parse import urlencode

import structlog

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
    DirectSearchListing,
    DirectSearchRequest,
    DirectSearchUpstreamProvider,
    DirectSearchUpstreamResult,
)
from osu_server.infrastructure.beatmaps.mappers import beatmap_json_to_snapshot

if TYPE_CHECKING:
    from osu_server.infrastructure.http.interfaces import BeatmapHttpClient

_EMPTY_MD5: Final = "0" * 32
_DEFAULT_USER_AGENT: Final = "Athena osu!direct search"

_MODE_QUERY_VALUES: Final[dict[BeatmapMode, str]] = {
    BeatmapMode.OSU: "0",
    BeatmapMode.TAIKO: "1",
    BeatmapMode.FRUITS: "2",
    BeatmapMode.MANIA: "3",
}
_CHEESEGULL_STATUS_QUERY_VALUES: Final[dict[BeatmapRankStatus, str]] = {
    BeatmapRankStatus.GRAVEYARD: "-2",
    BeatmapRankStatus.WIP: "-1",
    BeatmapRankStatus.PENDING: "0",
    BeatmapRankStatus.RANKED: "1",
    BeatmapRankStatus.APPROVED: "2",
    BeatmapRankStatus.QUALIFIED: "3",
    BeatmapRankStatus.LOVED: "4",
}
_CHEESEGULL_ALL_STATUS_QUERY_VARIANTS: Final = (
    BeatmapRankStatus.PENDING,
    BeatmapRankStatus.RANKED,
    BeatmapRankStatus.APPROVED,
    BeatmapRankStatus.QUALIFIED,
    BeatmapRankStatus.LOVED,
)
_CHEESEGULL_SORT_QUERY_VALUES: Final[dict[DirectSearchListing, str]] = {
    DirectSearchListing.NEWEST: "ranked_desc",
    DirectSearchListing.TOP_RATED: "favourites_desc",
    DirectSearchListing.MOST_PLAYED: "plays_desc",
}
_STATUS_TEXT_VALUES: Final[dict[int, str]] = {
    -2: "graveyard",
    -1: "wip",
    0: "pending",
    1: "ranked",
    2: "approved",
    3: "qualified",
    4: "loved",
}
_ROW_KEYS: Final = ("beatmapsets", "BeatmapSets", "results", "Results", "data")
_EARLIEST_DATETIME: Final = datetime.min.replace(tzinfo=UTC)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class CheeseGullDirectSearchUpstreamProvider:
    """CheeseGull互換JSON検索をDirectSearchUpstreamProviderへ変換するadapter.

    Attributes:
        _http_client (BeatmapHttpClient): JSON requestを実行するHTTP adapter.
        _search_url (str): CheeseGull互換検索endpointの絶対URL.
        _source_label (str): errorとlogに使うsource名.
        _headers (dict[str, str]): requestへ追加するHTTP header.
    """

    _http_client: BeatmapHttpClient
    _search_url: str
    _source_label: str
    _headers: dict[str, str]

    def __init__(
        self,
        *,
        http_client: BeatmapHttpClient,
        search_url: str,
        source_label: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """HTTP clientと検索endpointを保持する.

        Args:
            http_client (BeatmapHttpClient): JSON requestを実行するHTTP adapter.
            search_url (str): CheeseGull互換検索endpointの絶対URL.
            source_label (str): errorとlogに使うsource名.
            headers (Mapping[str, str] | None): requestへ追加するHTTP header.

        Raises:
            ValueError: search_urlまたはsource_labelが空の場合.
        """
        if not search_url.strip():
            msg = "search_url must not be empty"
            raise ValueError(msg)
        if not source_label.strip():
            msg = "source_label must not be empty"
            raise ValueError(msg)
        self._http_client = http_client
        self._search_url = search_url.strip()
        self._source_label = source_label.strip()
        self._headers = dict(headers or {"User-Agent": _DEFAULT_USER_AGENT})

    async def search(self, request: DirectSearchRequest) -> DirectSearchUpstreamResult:
        """CheeseGull互換検索endpointから外部候補を取得する.

        Args:
            request (DirectSearchRequest): stable inputから導出された検索条件.

        Returns:
            DirectSearchUpstreamResult: domain beatmapsetへ変換済みの外部候補.
        """
        return await _search_status_variants(
            request,
            statuses=_cheesegull_status_variants(request),
            sort_key=_beatmapset_last_update_sort_key if not request.statuses else None,
            search_one=self._search_one,
        )

    async def _search_one(
        self,
        request: DirectSearchRequest,
    ) -> DirectSearchUpstreamResult:
        """単一status条件のCheeseGull互換検索を実行する.

        Args:
            request (DirectSearchRequest): 0件または1件のstatus条件を持つ検索条件.

        Returns:
            DirectSearchUpstreamResult: domain beatmapsetへ変換済みの外部候補.
        """
        query = urlencode(_cheesegull_params(request))
        data = await self._http_client.fetch_json(
            f"{self._search_url}?{query}",
            source=self._source_label,
            lookup_key=_lookup_key(request),
            headers=self._headers,
        )
        rows = _extract_rows(data)
        status_override = _cheesegull_status_override(request)
        return _map_rows(
            rows,
            request.page_size,
            lambda row: _cheesegull_row_to_beatmapset(row, status_override=status_override),
        )


class NerinyanDirectSearchUpstreamProvider:
    """Nerinyan v2検索JSONをDirectSearchUpstreamProviderへ変換するadapter.

    Attributes:
        _http_client (BeatmapHttpClient): JSON requestを実行するHTTP adapter.
        _search_url (str): Nerinyan v2検索endpointの絶対URL.
        _headers (dict[str, str]): requestへ追加するHTTP header.
    """

    _http_client: BeatmapHttpClient
    _search_url: str
    _headers: dict[str, str]

    def __init__(
        self,
        *,
        http_client: BeatmapHttpClient,
        search_url: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """HTTP clientとNerinyan検索endpointを保持する.

        Args:
            http_client (BeatmapHttpClient): JSON requestを実行するHTTP adapter.
            search_url (str): Nerinyan v2検索endpointの絶対URL.
            headers (Mapping[str, str] | None): requestへ追加するHTTP header.

        Raises:
            ValueError: search_urlが空の場合.
        """
        if not search_url.strip():
            msg = "search_url must not be empty"
            raise ValueError(msg)
        self._http_client = http_client
        self._search_url = search_url.strip()
        self._headers = dict(headers or {})

    async def search(self, request: DirectSearchRequest) -> DirectSearchUpstreamResult:
        """Nerinyan v2検索endpointから外部候補を取得する.

        Args:
            request (DirectSearchRequest): stable inputから導出された検索条件.

        Returns:
            DirectSearchUpstreamResult: domain beatmapsetへ変換済みの外部候補.
        """
        return await _search_status_variants(request, search_one=self._search_one)

    async def _search_one(
        self,
        request: DirectSearchRequest,
    ) -> DirectSearchUpstreamResult:
        """単一status条件のNerinyan v2検索を実行する.

        Args:
            request (DirectSearchRequest): 0件または1件のstatus条件を持つ検索条件.

        Returns:
            DirectSearchUpstreamResult: domain beatmapsetへ変換済みの外部候補.
        """
        query = urlencode(_nerinyan_params(request))
        data = await self._http_client.fetch_json(
            f"{self._search_url}?{query}",
            source="nerinyan",
            lookup_key=_lookup_key(request),
            headers=self._headers,
        )
        rows = _extract_rows(data)
        result = _map_rows(rows, request.page_size, _v2_row_to_beatmapset)
        return DirectSearchUpstreamResult(
            beatmapsets=result.beatmapsets,
            has_more=result.has_more or _has_cursor(data),
        )


class SequentialDirectSearchUpstreamProvider:
    """設定順に外部検索providerを試すComposite adapter.

    Attributes:
        _providers (tuple[DirectSearchUpstreamProvider, ...]): 照会順のprovider列.
    """

    _providers: tuple[DirectSearchUpstreamProvider, ...]

    def __init__(self, providers: Sequence[DirectSearchUpstreamProvider]) -> None:
        """照会順のprovider列を保持する.

        Args:
            providers (Sequence[DirectSearchUpstreamProvider]): 外部検索provider列.

        Raises:
            ValueError: providersが空の場合.
        """
        if not providers:
            msg = "providers must not be empty"
            raise ValueError(msg)
        self._providers = tuple(providers)

    async def search(self, request: DirectSearchRequest) -> DirectSearchUpstreamResult:
        """最初に候補を返したproviderの結果を返す.

        Args:
            request (DirectSearchRequest): stable inputから導出された検索条件.

        Returns:
            DirectSearchUpstreamResult: 最初に候補を返したprovider結果. 全て空なら空結果.
        """
        for provider in self._providers:
            try:
                result = await provider.search(request)
            except Exception as exc:
                logger.warning(
                    "osu_direct_search_upstream_provider_failed",
                    provider=type(provider).__name__,
                    exception_type=type(exc).__name__,
                )
                continue
            if result.beatmapsets or result.has_more:
                return result
        return DirectSearchUpstreamResult(beatmapsets=(), has_more=False)


def _cheesegull_params(request: DirectSearchRequest) -> dict[str, str]:
    """CheeseGull互換検索endpointへ渡すquery parameterを構築する.

    Args:
        request (DirectSearchRequest): stable inputから導出された検索条件.

    Returns:
        dict[str, str]: query parameter名と値.
    """
    params = {
        "query": _cheesegull_query_text(request),
        "mode": _mode_query_value(request.mode),
        "amount": str(request.page_size),
        "offset": str(request.page * request.page_size),
    }
    status = _single_status(request.statuses)
    if status is not None and status in _CHEESEGULL_STATUS_QUERY_VALUES:
        params["status"] = _CHEESEGULL_STATUS_QUERY_VALUES[status]
    sort = _CHEESEGULL_SORT_QUERY_VALUES.get(request.listing)
    if sort is not None:
        params["sort"] = sort
    return params


def _cheesegull_query_text(request: DirectSearchRequest) -> str:
    """CheeseGull互換検索へ渡すtext queryをlisting種別から返す.

    Args:
        request (DirectSearchRequest): stable inputから導出された検索条件.

    Returns:
        str: 通常検索ではquery text, special listingでは空文字列.
    """
    if request.listing is DirectSearchListing.SEARCH:
        return request.query_text
    return ""


def _cheesegull_status_override(request: DirectSearchRequest) -> BeatmapRankStatus | None:
    """CheeseGull row statusをrequest条件から補正するstatusを返す.

    Args:
        request (DirectSearchRequest): stable inputから導出された検索条件.

    Returns:
        BeatmapRankStatus | None: v1 rowだけでは表現できないstatus補正. 補正不要ならNone.
    """
    status = _single_status(request.statuses)
    if status is BeatmapRankStatus.GRAVEYARD:
        return status
    return None


def _cheesegull_status_variants(
    request: DirectSearchRequest,
) -> tuple[BeatmapRankStatus, ...]:
    """CheeseGull v1へ送るstatus検索列を返す.

    Args:
        request (DirectSearchRequest): stable inputから導出された検索条件.

    Returns:
        tuple[BeatmapRankStatus, ...]: 明示filterがある場合はそのfilter. Allではv1が
            documented statusとして扱う公開status列.
    """
    if request.statuses:
        return request.statuses
    return _CHEESEGULL_ALL_STATUS_QUERY_VARIANTS


def _nerinyan_params(request: DirectSearchRequest) -> dict[str, str]:
    """Nerinyan v2検索endpointへ渡すquery parameterを構築する.

    Args:
        request (DirectSearchRequest): stable inputから導出された検索条件.

    Returns:
        dict[str, str]: query parameter名と値.
    """
    params = {
        "q": request.query_text,
        "m": _mode_query_value(request.mode),
        "p": str(request.page + 1),
        "ps": str(request.page_size),
    }
    status = _single_status(request.statuses)
    if status is not None:
        params["s"] = status.value
    return params


def _single_status(statuses: tuple[BeatmapRankStatus, ...]) -> BeatmapRankStatus | None:
    """単一status filterだけを外部provider queryへ反映する.

    Args:
        statuses (tuple[BeatmapRankStatus, ...]): direct search requestのstatus filter.

    Returns:
        BeatmapRankStatus | None: 1件だけ指定されたstatus. それ以外はNone.
    """
    return statuses[0] if len(statuses) == 1 else None


type _StatusVariantSearch = Callable[[DirectSearchRequest], Awaitable[DirectSearchUpstreamResult]]
type _StatusVariantSortKey = Callable[[BeatmapSet], tuple[datetime, int]]


async def _search_status_variants(
    request: DirectSearchRequest,
    *,
    search_one: _StatusVariantSearch,
    statuses: tuple[BeatmapRankStatus, ...] | None = None,
    sort_key: _StatusVariantSortKey | None = None,
) -> DirectSearchUpstreamResult:
    """複合status検索をproviderが表現できる単一status検索へ分解する.

    Args:
        request (DirectSearchRequest): stable inputから導出された検索条件.
        search_one (_StatusVariantSearch): 単一status条件で実行するprovider検索.
        statuses (tuple[BeatmapRankStatus, ...] | None): request statusの代わりに検索する
            status列. Noneならrequest.statusesを使う.
        sort_key (_StatusVariantSortKey | None): 複合結果を再整列するkey. Noneならprovider
            status列の順序を維持する.

    Returns:
        DirectSearchUpstreamResult: status別結果を重複排除してpage上限へ収めた候補.
    """
    variant_statuses = request.statuses if statuses is None else statuses
    if sort_key is not None and len(variant_statuses) > 1:
        return await _search_sorted_status_variants(
            request,
            variant_statuses,
            search_one=search_one,
            sort_key=sort_key,
        )
    if len(variant_statuses) <= 1:
        if variant_statuses == request.statuses:
            return await search_one(request)
        return await search_one(replace(request, statuses=variant_statuses))

    beatmapsets: list[BeatmapSet] = []
    seen_ids: set[int] = set()
    has_more = False
    should_collect_all = sort_key is not None
    for status in variant_statuses:
        result = await search_one(replace(request, statuses=(status,)))
        has_more = has_more or result.has_more
        for beatmapset in result.beatmapsets:
            if beatmapset.id in seen_ids:
                continue
            beatmapsets.append(beatmapset)
            seen_ids.add(beatmapset.id)
            if not should_collect_all and len(beatmapsets) >= request.page_size:
                return DirectSearchUpstreamResult(
                    beatmapsets=tuple(beatmapsets),
                    has_more=True,
                )

    if sort_key is not None:
        beatmapsets.sort(key=sort_key, reverse=True)

    return DirectSearchUpstreamResult(
        beatmapsets=tuple(beatmapsets[: request.page_size]),
        has_more=has_more or len(beatmapsets) > request.page_size,
    )


async def _search_sorted_status_variants(
    request: DirectSearchRequest,
    statuses: tuple[BeatmapRankStatus, ...],
    *,
    search_one: _StatusVariantSearch,
    sort_key: _StatusVariantSortKey,
) -> DirectSearchUpstreamResult:
    """Status別pageをglobal sort後のpageとして統合する.

    Args:
        request (DirectSearchRequest): stable inputから導出された検索条件.
        statuses (tuple[BeatmapRankStatus, ...]): 単一status queryへ分解するstatus列.
        search_one (_StatusVariantSearch): 単一status条件で実行するprovider検索.
        sort_key (_StatusVariantSortKey): status別結果をglobal順へ並べるkey.

    Returns:
        DirectSearchUpstreamResult: global offsetで切り出したstatus混在page.
    """
    beatmapsets: list[BeatmapSet] = []
    seen_ids: set[int] = set()
    has_more = False
    for status in statuses:
        for page in range(request.page + 1):
            result = await search_one(replace(request, statuses=(status,), page=page))
            if page == request.page:
                has_more = has_more or result.has_more
            for beatmapset in result.beatmapsets:
                if beatmapset.id in seen_ids:
                    continue
                beatmapsets.append(beatmapset)
                seen_ids.add(beatmapset.id)

    beatmapsets.sort(key=sort_key, reverse=True)
    offset = request.page * request.page_size
    end = offset + request.page_size
    return DirectSearchUpstreamResult(
        beatmapsets=tuple(beatmapsets[offset:end]),
        has_more=has_more or len(beatmapsets) > end,
    )


def _beatmapset_last_update_sort_key(beatmapset: BeatmapSet) -> tuple[datetime, int]:
    """Beatmapsetのofficial更新日時とIDを降順sort用keyとして返す.

    Args:
        beatmapset (BeatmapSet): CheeseGull status別結果から得たbeatmapset.

    Returns:
        tuple[datetime, int]: 更新日時がない場合は最古時刻,同時刻ではbeatmapset ID.
    """
    if beatmapset.official_last_updated_at is not None:
        return (beatmapset.official_last_updated_at, beatmapset.id)
    last_update_at = max(
        (
            beatmap.official_last_updated_at
            for beatmap in beatmapset.beatmaps
            if beatmap.official_last_updated_at is not None
        ),
        default=_EARLIEST_DATETIME,
    )
    return (last_update_at, beatmapset.id)


def _mode_query_value(mode: BeatmapMode | None) -> str:
    """DirectSearchRequestのmode filterをmirror query値へ変換する.

    Args:
        mode (BeatmapMode | None): requestのmode filter. Noneなら全mode.

    Returns:
        str: mirror queryへ渡すmode値.
    """
    if mode is None:
        return "-1"
    return _MODE_QUERY_VALUES.get(mode, "-1")


def _lookup_key(request: DirectSearchRequest) -> str:
    """HTTP error分類に使う検索keyを構築する.

    Args:
        request (DirectSearchRequest): stable inputから導出された検索条件.

    Returns:
        str: source errorとlogに残す検索key.
    """
    if request.query_text:
        return request.query_text
    if request.listing is DirectSearchListing.SEARCH:
        return "search"
    return request.listing.value


def _extract_rows(data: dict[str, object] | list[object]) -> tuple[object, ...]:
    """外部検索JSONから候補row配列を取り出す.

    Args:
        data (dict[str, object] | list[object]): providerが返したtop-level JSON.

    Returns:
        tuple[object, ...]: 候補row列. 未対応shapeでは空tuple.
    """
    if isinstance(data, list):
        return tuple(data)
    for key in _ROW_KEYS:
        value = data.get(key)
        if isinstance(value, list):
            return tuple(cast("list[object]", value))
    return ()


def _has_cursor(data: dict[str, object] | list[object]) -> bool:
    """Nerinyan v2風responseに次page cursorがあるか返す.

    Args:
        data (dict[str, object] | list[object]): providerが返したtop-level JSON.

    Returns:
        bool: cursor fieldが空でない場合はTrue.
    """
    return isinstance(data, dict) and data.get("cursor") is not None


def _map_rows(
    rows: tuple[object, ...],
    page_size: int,
    mapper: MappingFunction,
) -> DirectSearchUpstreamResult:
    """外部row列をdomain beatmapsetへ変換してpage上限で切る.

    Args:
        rows (tuple[object, ...]): 外部検索が返したrow列.
        page_size (int): 呼び出し元へ返す最大件数.
        mapper (MappingFunction): provider方言のrow変換関数.

    Returns:
        DirectSearchUpstreamResult: 変換できた候補と次page有無.
    """
    beatmapsets: list[BeatmapSet] = []
    for row in rows[: page_size + 1]:
        if not isinstance(row, Mapping):
            continue
        try:
            beatmapset = mapper(cast("Mapping[str, object]", row))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "osu_direct_search_upstream_row_invalid",
                exception_type=type(exc).__name__,
            )
            continue
        if beatmapset is not None:
            beatmapsets.append(beatmapset)
    return DirectSearchUpstreamResult(
        beatmapsets=tuple(beatmapsets[:page_size]),
        has_more=len(rows) >= page_size or len(beatmapsets) > page_size,
    )


type MappingFunction = Callable[[Mapping[str, object]], BeatmapSet | None]


def _cheesegull_row_to_beatmapset(
    row: Mapping[str, object],
    *,
    status_override: BeatmapRankStatus | None = None,
) -> BeatmapSet | None:
    """CheeseGull互換rowをdomain beatmapsetへ変換する.

    Args:
        row (Mapping[str, object]): CheeseGull互換の検索row.
        status_override (BeatmapRankStatus | None): rowのRankedStatusより優先するstatus.

    Returns:
        BeatmapSet | None: 変換できたdomain beatmapset. 必須IDがない場合はNone.
    """
    beatmapset_id = _maybe_int(row.get("SetID"))
    if beatmapset_id is None or beatmapset_id <= 0:
        return None

    status = (
        status_override.value
        if status_override is not None
        else _status_text(row.get("RankedStatus"))
    )
    children = row.get("ChildrenBeatmaps")
    child_rows = cast("list[object]", children) if isinstance(children, list) else []
    normalized: dict[str, object] = {
        "id": beatmapset_id,
        "artist": _maybe_str(row.get("Artist")) or "",
        "title": _maybe_str(row.get("Title")) or "",
        "creator": _maybe_str(row.get("Creator")) or "",
        "artist_unicode": _maybe_str(row.get("ArtistUnicode")),
        "title_unicode": _maybe_str(row.get("TitleUnicode")),
        "source": _maybe_str(row.get("Source")) or "",
        "tags": _maybe_str(row.get("Tags")) or "",
        "status": status,
        "submitted_date": (
            _maybe_str(row.get("SubmittedDate")) or _maybe_str(row.get("submitted_date"))
        ),
        "ranked_date": (
            _maybe_str(row.get("RankedDate"))
            or _maybe_str(row.get("ranked_date"))
            or _maybe_str(row.get("ApprovedDate"))
            or _maybe_str(row.get("approved_date"))
        ),
        "last_updated": _maybe_str(row.get("LastUpdate")) or _maybe_str(row.get("last_updated")),
        "beatmaps": [
            _cheesegull_child_to_v2_json(
                cast("Mapping[object, object]", child),
                beatmapset_id,
                status,
            )
            for child in child_rows
            if isinstance(child, Mapping)
        ],
    }
    return _snapshot_to_beatmapset(
        beatmap_json_to_snapshot(
            normalized,
            source=BeatmapMetadataSource.MIRROR,
            verification=BeatmapSourceVerification.UNVERIFIED,
        )
    )


def _cheesegull_child_to_v2_json(
    child: Mapping[object, object],
    beatmapset_id: int,
    status: str,
) -> dict[str, object]:
    """CheeseGull child rowを既存v2 mapperが読めるJSONへ変換する.

    Args:
        child (Mapping[object, object]): CheeseGull互換child row.
        beatmapset_id (int): 親beatmapset ID.
        status (str): 親rowから導出した公開status名.

    Returns:
        dict[str, object]: osu API v2風のchild beatmap JSON.
    """
    return {
        "id": _maybe_int(child.get("BeatmapID")) or 0,
        "beatmapset_id": beatmapset_id,
        "checksum": _maybe_str(child.get("FileMD5")) or _EMPTY_MD5,
        "mode": _maybe_int(child.get("Mode")) if child.get("Mode") is not None else -1,
        "version": _maybe_str(child.get("DiffName")) or "",
        "status": status,
        "total_length": _maybe_int(child.get("TotalLength")),
        "hit_length": _maybe_int(child.get("HitLength")),
        "max_combo": _maybe_int(child.get("MaxCombo")),
        "bpm": _maybe_float(child.get("BPM")),
        "cs": _maybe_float(child.get("CS")),
        "accuracy": _maybe_float(child.get("OD")),
        "ar": _maybe_float(child.get("AR")),
        "drain": _maybe_float(child.get("HP")),
        "difficulty_rating": _maybe_float(child.get("DifficultyRating")),
        "last_updated": _maybe_str(child.get("LastUpdate")),
    }


def _v2_row_to_beatmapset(row: Mapping[str, object]) -> BeatmapSet | None:
    """Osu API v2風rowをdomain beatmapsetへ変換する.

    Args:
        row (Mapping[str, object]): osu API v2風のbeatmapset row.

    Returns:
        BeatmapSet | None: 変換できたdomain beatmapset. 必須IDがない場合はNone.
    """
    if (_maybe_int(row.get("id")) or 0) <= 0:
        return None
    return _snapshot_to_beatmapset(
        beatmap_json_to_snapshot(
            dict(row),
            source=BeatmapMetadataSource.MIRROR,
            verification=BeatmapSourceVerification.UNVERIFIED,
        )
    )


def _snapshot_to_beatmapset(snapshot: BeatmapsetSnapshot) -> BeatmapSet:
    """Provider snapshotをsearch response用domain beatmapsetへ変換する.

    Args:
        snapshot (BeatmapsetSnapshot): provider JSONから変換したmetadata snapshot.

    Returns:
        BeatmapSet: stable formatterが扱えるdomain beatmapset.
    """
    return BeatmapSet(
        id=snapshot.beatmapset_id,
        artist=snapshot.artist,
        title=snapshot.title,
        creator=snapshot.creator,
        artist_unicode=snapshot.artist_unicode,
        title_unicode=snapshot.title_unicode,
        official_status=snapshot.official_status,
        official_status_source=snapshot.official_status_source,
        official_status_verified=snapshot.official_status_verified,
        beatmaps=tuple(_snapshot_to_beatmap(beatmap) for beatmap in snapshot.beatmaps),
        last_fetched_at=snapshot.last_fetched_at,
        next_refresh_at=snapshot.next_refresh_at,
        official_submitted_at=snapshot.official_submitted_at,
        official_ranked_at=snapshot.official_ranked_at,
        official_last_updated_at=snapshot.official_last_updated_at,
        source_text=snapshot.source_text,
        tags=snapshot.tags,
    )


def _snapshot_to_beatmap(snapshot: BeatmapSnapshot) -> Beatmap:
    """Provider snapshotをsearch response用domain beatmapへ変換する.

    Args:
        snapshot (BeatmapSnapshot): provider JSONから変換したchild metadata snapshot.

    Returns:
        Beatmap: stable formatterが扱えるdomain beatmap.
    """
    return Beatmap(
        id=snapshot.beatmap_id,
        beatmapset_id=snapshot.beatmapset_id,
        checksum_md5=snapshot.checksum_md5,
        mode=snapshot.mode,
        version=snapshot.version,
        total_length=snapshot.total_length,
        hit_length=snapshot.hit_length,
        max_combo=snapshot.max_combo,
        bpm=snapshot.bpm,
        cs=snapshot.cs,
        od=snapshot.od,
        ar=snapshot.ar,
        hp=snapshot.hp,
        difficulty_rating=snapshot.difficulty_rating,
        official_status=snapshot.official_status,
        official_status_source=snapshot.official_status_source,
        official_status_verified=snapshot.official_status_verified,
        local_status_override=snapshot.local_status_override,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=snapshot.last_fetched_at,
        next_refresh_at=snapshot.next_refresh_at,
        official_last_updated_at=snapshot.official_last_updated_at,
    )


def _status_text(value: object) -> str:
    """外部JSONの数値statusまたは文字列statusをdomain mapper用文字列へ変換する.

    Args:
        value (object): providerが返したstatus値.

    Returns:
        str: 数値statusに対応する名称,または前後空白を除いた文字列. 未対応値は空文字列.
    """
    status = _maybe_int(value)
    if status is not None:
        return _STATUS_TEXT_VALUES.get(status, "")
    return (_maybe_str(value) or "").strip()


def _maybe_int(value: object) -> int | None:
    """外部JSON値をintへ安全に変換する.

    Args:
        value (object): 外部APIから受け取った変換対象値.

    Returns:
        int | None: 変換した整数. bool, None, 不正な文字列, 未対応型はNone.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _maybe_float(value: object) -> float | None:
    """外部JSON値をfloatへ安全に変換する.

    Args:
        value (object): 外部APIから受け取った変換対象値.

    Returns:
        float | None: 変換した浮動小数点数. bool, None, 不正な文字列, 未対応型はNone.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _maybe_str(value: object) -> str | None:
    """外部JSON値を文字列として扱える場合だけ文字列化する.

    Args:
        value (object): 外部APIから受け取った変換対象値.

    Returns:
        str | None: 文字列値,またはint/floatを文字列化した値. 未対応型とNoneはNone.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return str(value)
    return None


__all__ = [
    "CheeseGullDirectSearchUpstreamProvider",
    "NerinyanDirectSearchUpstreamProvider",
    "SequentialDirectSearchUpstreamProvider",
]
