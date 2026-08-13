"""Meilisearch向けosu!direct index/search adapterを提供するmodule."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from meilisearch_python_sdk.errors import MeilisearchError
from meilisearch_python_sdk.models.settings import MeilisearchSettings

from osu_server.domain.beatmaps.direct import (
    DirectSearchBackendResult,
    DirectSearchBackendUnavailableError,
    DirectSearchCandidate,
    DirectSearchListing,
    DirectSearchRequest,
)
from osu_server.infrastructure.search.direct_index_definition import (
    DIRECT_SEARCH_INDEX_DEFINITION,
    SearchIndexDefinition,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from typing import Protocol

    from meilisearch_python_sdk import AsyncClient as MeilisearchAsyncClient
    from meilisearch_python_sdk.index import AsyncIndex
    from meilisearch_python_sdk.models.search import SearchResults

    from osu_server.domain.beatmaps.direct import BeatmapSetSearchDocument

    class _MeilisearchSearchIndex(Protocol):
        """Meilisearch search()のhit型だけを固定するtyping用Protocol."""

        async def search(
            self,
            query: str | None = None,
            **options: object,
        ) -> SearchResults[dict[str, object]]:
            """Search result hitをdictとして返す.

            Args:
                query (str | None): 検索query text.
                **options (object): Meilisearch SDKへ渡す検索option.

            Returns:
                SearchResults[dict[str, object]]: dict hitを含む検索結果.
            """
            ...


_BACKEND_NAME: Final = "meilisearch"
_ACTIVE_FIELD: Final = "is_active"
_PRIMARY_KEY_FIELD: Final = "beatmapset_id"
_RANKING_SCORE_FIELD: Final = "_rankingScore"
_FALLBACK_SCORE: Final = 0.0


class MeilisearchDirectIndexError(RuntimeError):
    """Meilisearch external index更新のretry可能な失敗を表す.

    Attributes:
        beatmapset_id (int | None): 失敗したdocumentのbeatmapset ID. settings更新ならNone.
        document_version (int | None): 失敗したprojection version. settings更新ならNone.
    """

    beatmapset_id: int | None
    document_version: int | None

    def __init__(
        self,
        message: str,
        *,
        beatmapset_id: int | None = None,
        document_version: int | None = None,
    ) -> None:
        """Sanitized messageとretry状態に使うdocument identityを保持する.

        Args:
            message (str): credentialやresponse bodyを含まない失敗理由.
            beatmapset_id (int | None): 失敗したdocumentのbeatmapset ID.
            document_version (int | None): 失敗したprojection version.
        """
        super().__init__(message)
        self.beatmapset_id = beatmapset_id
        self.document_version = document_version


class MeilisearchDirectSearchBackendUnavailableError(DirectSearchBackendUnavailableError):
    """Meilisearch search backendの必須capability不足を表す例外."""


class MeilisearchDirectIndexBackend:
    """Meilisearchへosu!direct projection documentを同期するadapter.

    Attributes:
        _client (MeilisearchAsyncClient): lifecycleを呼び出し側が所有するSDK client.
        _index_name (str): Meilisearch index UID.
        _index_definition (SearchIndexDefinition): settingsとdocument fieldの共有宣言.
    """

    _client: MeilisearchAsyncClient
    _index_name: str
    _index_definition: SearchIndexDefinition

    def __init__(
        self,
        *,
        client: MeilisearchAsyncClient,
        index_name: str,
        index_definition: SearchIndexDefinition = DIRECT_SEARCH_INDEX_DEFINITION,
    ) -> None:
        """SDK clientとMeilisearch index設定を保持する.

        Args:
            client (MeilisearchAsyncClient): Meilisearch SDK async client.
            index_name (str): osu!direct用Meilisearch index UID.
            index_definition (SearchIndexDefinition): 共有field宣言.

        Raises:
            ValueError: index_nameが空の場合.
        """
        if not index_name.strip():
            msg = "index_name must not be empty"
            raise ValueError(msg)
        self._client = client
        self._index_name = index_name.strip()
        self._index_definition = index_definition

    async def apply_settings(self) -> None:
        """共有field宣言をMeilisearch settingsへ適用する.

        Returns:
            None: settings更新requestがMeilisearchへ受理されたことを示す.

        Raises:
            MeilisearchDirectIndexError: Meilisearch requestが失敗した場合.
        """
        try:
            _ = await self._index().update_settings(_settings_payload(self._index_definition))
        except MeilisearchError as exc:
            msg = f"{_BACKEND_NAME} settings update failed"
            raise MeilisearchDirectIndexError(msg) from exc

    async def index_document(self, document: BeatmapSetSearchDocument) -> None:
        """Committed projection documentをMeilisearchへ同期する.

        Args:
            document (BeatmapSetSearchDocument): DB commit後に読み直したprojection document.

        Returns:
            None: document更新requestがMeilisearchへ受理されたことを示す.

        Raises:
            MeilisearchDirectIndexError: Meilisearch requestが失敗した場合.
        """
        try:
            _ = await self._index().add_documents(
                [_document_payload(document, self._index_definition)],
                primary_key=_PRIMARY_KEY_FIELD,
            )
        except MeilisearchError as exc:
            msg = f"{_BACKEND_NAME} document indexing failed"
            raise MeilisearchDirectIndexError(
                msg,
                beatmapset_id=document.beatmapset_id,
                document_version=document.document_version,
            ) from exc

    def _index(self) -> AsyncIndex:
        """設定済みindex UIDのSDK index handleを返す.

        Returns:
            AsyncIndex: Meilisearch SDKが生成するlocal index handle.
        """
        return self._client.index(self._index_name)


class MeilisearchDirectSearchBackend:
    """Meilisearch indexからosu!direct候補IDとscoreを取得するbackend.

    Attributes:
        _client (MeilisearchAsyncClient): lifecycleを呼び出し側が所有するSDK client.
        _index_name (str): Meilisearch index UID.
        _index_definition (SearchIndexDefinition): settingsとdocument fieldの共有宣言.
    """

    _client: MeilisearchAsyncClient
    _index_name: str
    _index_definition: SearchIndexDefinition

    def __init__(
        self,
        *,
        client: MeilisearchAsyncClient,
        index_name: str,
        index_definition: SearchIndexDefinition = DIRECT_SEARCH_INDEX_DEFINITION,
    ) -> None:
        """SDK clientとMeilisearch index設定を保持する.

        Args:
            client (MeilisearchAsyncClient): Meilisearch SDK async client.
            index_name (str): osu!direct用Meilisearch index UID.
            index_definition (SearchIndexDefinition): 共有field宣言.

        Raises:
            ValueError: index_nameが空の場合.
        """
        if not index_name.strip():
            msg = "index_name must not be empty"
            raise ValueError(msg)
        self._client = client
        self._index_name = index_name.strip()
        self._index_definition = index_definition

    async def search(self, request: DirectSearchRequest) -> DirectSearchBackendResult:
        """Meilisearchから検索候補IDとscoreだけを返す.

        Args:
            request (DirectSearchRequest): stable inputから導出された検索条件.

        Returns:
            DirectSearchBackendResult: page内候補と次page有無.

        Raises:
            MeilisearchDirectSearchBackendUnavailableError: Meilisearch search APIに失敗した場合.
            KeyError: hitに必須fieldがない場合.
            TypeError: hitの必須field型が期待値と異なる場合.
        """
        try:
            search_index = cast("_MeilisearchSearchIndex", cast("object", self._index()))
            result = await search_index.search(
                _query_text(request),
                offset=request.page * request.page_size,
                limit=request.page_size + 1,
                filter=_filter_expression(request),
                sort=_sort_fields(request),
                attributes_to_retrieve=[_PRIMARY_KEY_FIELD],
                show_ranking_score=True,
            )
        except MeilisearchError as exc:
            msg = f"{_BACKEND_NAME} search request failed"
            raise MeilisearchDirectSearchBackendUnavailableError(msg) from exc

        hits = cast("Sequence[dict[str, object]]", result.hits)
        candidate_rows = hits[: request.page_size]
        return DirectSearchBackendResult(
            candidates=tuple(_candidate_from_hit(hit) for hit in candidate_rows),
            has_more=len(hits) > request.page_size,
        )

    async def validate(self) -> None:
        """Meilisearch serverとindex settingsが検索可能か検証する.

        Returns:
            None: server, index, settingsが検索trafficを受けられることを示す.

        Raises:
            MeilisearchDirectSearchBackendUnavailableError: server, index, settingsが不足する場合.
        """
        try:
            health = await self._client.health()
            settings = await self._index().get_settings()
        except MeilisearchError as exc:
            msg = f"{_BACKEND_NAME} search backend is unavailable"
            raise MeilisearchDirectSearchBackendUnavailableError(msg) from exc

        if health.status != "available":
            msg = f"{_BACKEND_NAME} search backend health is {health.status}"
            raise MeilisearchDirectSearchBackendUnavailableError(msg)

        missing_fields = _missing_settings_fields(settings, self._index_definition)
        if missing_fields:
            msg = (
                f"{_BACKEND_NAME} search index is missing settings fields: "
                f"{', '.join(missing_fields)}"
            )
            raise MeilisearchDirectSearchBackendUnavailableError(msg)

    def _index(self) -> AsyncIndex:
        """設定済みindex UIDのSDK index handleを返す.

        Returns:
            AsyncIndex: Meilisearch SDKが生成するlocal index handle.
        """
        return self._client.index(self._index_name)


def _settings_payload(index_definition: SearchIndexDefinition) -> MeilisearchSettings:
    """共有field宣言をMeilisearch SDK settings modelへ変換する.

    Args:
        index_definition (SearchIndexDefinition): external indexへ公開するfield宣言.

    Returns:
        MeilisearchSettings: SDKに渡すsettings payload.
    """
    return MeilisearchSettings(
        searchable_attributes=list(index_definition.searchable_fields),
        filterable_attributes=list(_meilisearch_filterable_fields(index_definition)),
        sortable_attributes=list(index_definition.sortable_fields),
        displayed_attributes=list(_meilisearch_displayed_fields(index_definition)),
    )


def _meilisearch_filterable_fields(
    index_definition: SearchIndexDefinition,
) -> tuple[str, ...]:
    """Meilisearch検索に必要なfilterable fieldを返す.

    Args:
        index_definition (SearchIndexDefinition): external indexへ公開するfield宣言.

    Returns:
        tuple[str, ...]: shared filterable fieldにactive判定fieldを加えたfield列.
    """
    return tuple(dict.fromkeys((*index_definition.filterable_fields, _ACTIVE_FIELD)))


def _meilisearch_displayed_fields(
    index_definition: SearchIndexDefinition,
) -> tuple[str, ...]:
    """Meilisearch documentへ同期するdisplayed fieldを返す.

    Args:
        index_definition (SearchIndexDefinition): external indexへ公開するfield宣言.

    Returns:
        tuple[str, ...]: shared displayed fieldにactive判定fieldを加えたfield列.
    """
    return tuple(dict.fromkeys((*index_definition.displayed_fields, _ACTIVE_FIELD)))


def _document_payload(
    document: BeatmapSetSearchDocument,
    index_definition: SearchIndexDefinition,
) -> dict[str, object]:
    """共有宣言に含まれるfieldだけをMeilisearch document payloadへ変換する.

    Args:
        document (BeatmapSetSearchDocument): committed projectionから読んだdocument.
        index_definition (SearchIndexDefinition): external indexへ公開するfield宣言.

    Returns:
        dict[str, object]: wire-safeなMeilisearch document.
    """
    source: dict[str, object] = {
        "artist": document.artist,
        "title": document.title,
        "creator": document.creator,
        "source": document.source,
        "tags": document.tags,
        "difficulty_names": document.difficulty_names,
        "artist_unicode": document.artist_unicode,
        "title_unicode": document.title_unicode,
        "status": document.status.value,
        "modes": [mode.value for mode in document.modes],
        "is_active": document.is_active,
        "beatmapset_id": document.beatmapset_id,
        "last_update_at": _optional_datetime(document.last_update_at),
        "document_version": document.document_version,
    }
    payload: dict[str, object] = {}
    for field in _document_fields(index_definition):
        payload[field] = source[field]
    return payload


def _document_fields(index_definition: SearchIndexDefinition) -> tuple[str, ...]:
    """External documentに含める宣言済みfieldを重複なしで返す.

    Args:
        index_definition (SearchIndexDefinition): external indexへ公開するfield宣言.

    Returns:
        tuple[str, ...]: searchable, filterable, sortable, displayedの順に重複除去したfield名.
    """
    return tuple(
        dict.fromkeys(
            (
                *index_definition.searchable_fields,
                *_meilisearch_filterable_fields(index_definition),
                *index_definition.sortable_fields,
                *_meilisearch_displayed_fields(index_definition),
            )
        )
    )


def _query_text(request: DirectSearchRequest) -> str:
    """Meilisearchへ渡すquery textを検索種別から決定する.

    Args:
        request (DirectSearchRequest): backendへ渡された検索条件.

    Returns:
        str: 通常text検索なら空白除去済みquery, special listingなら空文字列.
    """
    if request.listing is DirectSearchListing.SEARCH:
        return request.query_text.strip()
    return ""


def _filter_expression(request: DirectSearchRequest) -> str:
    """Direct search requestをMeilisearch filter expressionへ変換する.

    Args:
        request (DirectSearchRequest): backendへ渡された検索条件.

    Returns:
        str: active判定とstatus/mode条件を含むfilter expression.
    """
    filters = [f"{_ACTIVE_FIELD} = true"]
    if request.statuses:
        filters.append(
            "(" + " OR ".join(f"status = {status.value}" for status in request.statuses) + ")"
        )
    if request.mode is not None:
        filters.append(f"modes = {request.mode.value}")
    return " AND ".join(filters)


def _sort_fields(request: DirectSearchRequest) -> list[str] | None:
    """Direct search request用のMeilisearch sort fieldを返す.

    Args:
        request (DirectSearchRequest): backendへ渡された検索条件.

    Returns:
        list[str] | None: text検索ではMeilisearch rankingを優先し, listingではfallback順を返す.
    """
    if request.listing is DirectSearchListing.SEARCH and request.query_text.strip():
        return None
    return ["last_update_at:desc", "beatmapset_id:desc"]


def _candidate_from_hit(hit: dict[str, object]) -> DirectSearchCandidate:
    """Meilisearch hitを検索候補valueへ変換する.

    Args:
        hit (dict[str, object]): `beatmapset_id`と任意の`_rankingScore`を含むsearch hit.

    Returns:
        DirectSearchCandidate: hydration前の候補IDとscore.

    Raises:
        KeyError: 必須fieldがhitにない場合.
        TypeError: 必須field型が期待値と異なる場合.
    """
    score = hit.get(_RANKING_SCORE_FIELD, _FALLBACK_SCORE)
    return DirectSearchCandidate(
        beatmapset_id=_int_field(hit, _PRIMARY_KEY_FIELD),
        score=_numeric_value(score, _RANKING_SCORE_FIELD),
    )


def _missing_settings_fields(
    settings: MeilisearchSettings,
    index_definition: SearchIndexDefinition,
) -> tuple[str, ...]:
    """Meilisearch settingsから検索に必要な不足fieldを返す.

    Args:
        settings (MeilisearchSettings): Meilisearch indexから取得したsettings.
        index_definition (SearchIndexDefinition): external indexへ公開するfield宣言.

    Returns:
        tuple[str, ...]: 不足しているsettings fieldの説明列.
    """
    missing: list[str] = []
    missing.extend(
        f"searchableAttributes.{field}"
        for field in _missing_fields(
            index_definition.searchable_fields,
            settings.searchable_attributes,
        )
    )
    missing.extend(
        f"filterableAttributes.{field}"
        for field in _missing_fields(
            _meilisearch_filterable_fields(index_definition),
            settings.filterable_attributes,
        )
    )
    missing.extend(
        f"sortableAttributes.{field}"
        for field in _missing_fields(
            index_definition.sortable_fields,
            settings.sortable_attributes,
        )
    )
    missing.extend(
        f"displayedAttributes.{field}"
        for field in _missing_fields(
            _meilisearch_displayed_fields(index_definition),
            settings.displayed_attributes,
        )
    )
    return tuple(missing)


def _missing_fields(
    required_fields: Sequence[str],
    actual_fields: Sequence[object] | None,
) -> tuple[str, ...]:
    """Required field列のうちMeilisearch settingsにないfieldを返す.

    Args:
        required_fields (Sequence[str]): 検索に必要なfield列.
        actual_fields (Sequence[object] | None): Meilisearch settings上のfield列.

    Returns:
        tuple[str, ...]: 不足field列. `*` がある場合は空tuple.
    """
    if actual_fields is None:
        return tuple(required_fields)
    actual_names = {field for field in actual_fields if isinstance(field, str)}
    if "*" in actual_names:
        return ()
    return tuple(field for field in required_fields if field not in actual_names)


def _int_field(row: dict[str, object], field: str) -> int:
    """Mapping rowからboolではないint fieldを取り出す.

    Args:
        row (dict[str, object]): Meilisearch search hit.
        field (str): 取得するfield名.

    Returns:
        int: hit内のint値.

    Raises:
        KeyError: fieldがhitにない場合.
        TypeError: field値がintでない場合.
    """
    value = row[field]
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{field} must be int"
        raise TypeError(msg)
    return value


def _numeric_value(value: object, field: str) -> float:
    """Meilisearch hitからfloat化できる数値を取り出す.

    Args:
        value (object): hit内のscore値.
        field (str): 取得元field名.

    Returns:
        float: hit内のscore値.

    Raises:
        TypeError: field値が数値でない場合.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{field} must be numeric"
        raise TypeError(msg)
    return float(value)


def _optional_datetime(value: datetime | None) -> str | None:
    """任意datetimeをMeilisearch document用のISO 8601文字列へ変換する.

    Args:
        value (datetime | None): projection documentのdatetime field.

    Returns:
        str | None: datetimeがあればISO 8601文字列, なければNone.
    """
    if value is None:
        return None
    return value.isoformat()


__all__ = [
    "MeilisearchDirectIndexBackend",
    "MeilisearchDirectIndexError",
    "MeilisearchDirectSearchBackend",
    "MeilisearchDirectSearchBackendUnavailableError",
]
