"""Meilisearch osu!direct adapterのSDK contractを検証するmodule."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from meilisearch_python_sdk.errors import MeilisearchError
from meilisearch_python_sdk.models.health import Health
from meilisearch_python_sdk.models.search import SearchResults
from meilisearch_python_sdk.models.settings import MeilisearchSettings

from osu_server.domain.beatmaps.direct import (
    BeatmapSetSearchDocument,
    DirectSearchCandidate,
    DirectSearchRequest,
)
from osu_server.domain.beatmaps.models import BeatmapMode, BeatmapRankStatus
from osu_server.infrastructure.search.direct_index_definition import (
    DIRECT_SEARCH_INDEX_DEFINITION,
)
from osu_server.infrastructure.search.meilisearch_direct import (
    MeilisearchDirectIndexBackend,
    MeilisearchDirectIndexError,
    MeilisearchDirectSearchBackend,
    MeilisearchDirectSearchBackendUnavailableError,
)

if TYPE_CHECKING:
    from meilisearch_python_sdk import AsyncClient as MeilisearchAsyncClient


class FakeMeilisearchIndex:
    """Meilisearch SDK indexの必要なasync methodだけを提供する.

    Attributes:
        settings_updates (list[MeilisearchSettings]): update_settingsで受け取ったsettings列.
        document_batches (list[tuple[list[dict[str, object]], str | None]]):
            add_documentsで受け取ったdocument batchとprimary key.
        search_requests (list[dict[str, object]]): searchで受け取ったquery/options列.
        settings (MeilisearchSettings): get_settingsが返すsettings.
        search_result (SearchResults[dict[str, object]]): searchが返すresult.
        error (MeilisearchError | None): SDK失敗を再現する例外.
    """

    settings_updates: list[MeilisearchSettings]
    document_batches: list[tuple[list[dict[str, object]], str | None]]
    search_requests: list[dict[str, object]]
    settings: MeilisearchSettings
    search_result: SearchResults[dict[str, object]]
    error: MeilisearchError | None

    def __init__(self) -> None:
        """成功応答を返すfake indexを初期化する."""
        self.settings_updates = []
        self.document_batches = []
        self.search_requests = []
        self.settings = _valid_settings()
        self.search_result = SearchResults[dict[str, object]].model_validate(
            {
                "hits": [],
                "offset": 0,
                "limit": 20,
                "estimatedTotalHits": 0,
                "processingTimeMs": 1,
                "query": "",
            }
        )
        self.error = None

    async def update_settings(self, body: MeilisearchSettings) -> object:
        """渡されたsettingsを記録してtask風objectを返す.

        Args:
            body (MeilisearchSettings): adapterがSDKへ渡したsettings.

        Returns:
            object: adapterが内容を読まないtask placeholder.

        Raises:
            MeilisearchError: errorが設定されている場合.
        """
        if self.error is not None:
            raise self.error
        self.settings_updates.append(body)
        return SimpleNamespace(task_uid=1)

    async def add_documents(
        self,
        documents: list[dict[str, object]],
        primary_key: str | None = None,
    ) -> object:
        """渡されたdocument batchを記録してtask風objectを返す.

        Args:
            documents (list[dict[str, object]]): adapterがSDKへ渡したdocument列.
            primary_key (str | None): adapterが指定したprimary key.

        Returns:
            object: adapterが内容を読まないtask placeholder.

        Raises:
            MeilisearchError: errorが設定されている場合.
        """
        if self.error is not None:
            raise self.error
        self.document_batches.append((documents, primary_key))
        return SimpleNamespace(task_uid=2)

    async def search(
        self,
        query: str | None = None,
        **options: object,
    ) -> SearchResults[dict[str, object]]:
        """渡されたsearch queryとoptionsを記録して検索結果を返す.

        Args:
            query (str | None): adapterがSDKへ渡したquery.
            **options (object): adapterがSDKへ渡した検索option.

        Returns:
            SearchResults[dict[str, object]]: 設定済みsearch result.

        Raises:
            MeilisearchError: errorが設定されている場合.
        """
        if self.error is not None:
            raise self.error
        self.search_requests.append({"query": query, **options})
        return self.search_result

    async def get_settings(self) -> MeilisearchSettings:
        """設定済みsettingsを返す.

        Returns:
            MeilisearchSettings: validate用のindex settings.

        Raises:
            MeilisearchError: errorが設定されている場合.
        """
        if self.error is not None:
            raise self.error
        return self.settings


class FakeMeilisearchClient:
    """Meilisearch SDK clientの必要なmethodだけを提供する.

    Attributes:
        index_uid (str | None): index()で最後に指定されたUID.
        index_handle (FakeMeilisearchIndex): index()が返すfake index.
        health_status (str): health()が返すstatus.
        health_calls (int): health()呼び出し回数.
        waited_task_uids (list[int]): wait_for_taskで待機したtask UID列.
    """

    index_uid: str | None
    index_handle: FakeMeilisearchIndex
    health_status: str
    health_calls: int
    waited_task_uids: list[int]

    def __init__(self) -> None:
        """健康なMeilisearch client fakeを初期化する."""
        self.index_uid = None
        self.index_handle = FakeMeilisearchIndex()
        self.health_status = "available"
        self.health_calls = 0
        self.waited_task_uids = []

    def index(self, uid: str) -> FakeMeilisearchIndex:
        """指定UIDのfake index handleを返す.

        Args:
            uid (str): adapterが指定したMeilisearch index UID.

        Returns:
            FakeMeilisearchIndex: SDK index相当のfake.
        """
        self.index_uid = uid
        return self.index_handle

    async def health(self) -> Health:
        """設定済みhealth statusを返す.

        Returns:
            Health: Meilisearch SDK health model.
        """
        self.health_calls += 1
        return Health(status=self.health_status)

    async def wait_for_task(
        self,
        task_uid: int,
        *,
        timeout_in_ms: int | None = 5000,
        interval_in_ms: int = 50,
        raise_for_status: bool = False,
    ) -> object:
        """Meilisearch task完了待機呼び出しを記録する.

        Args:
            task_uid (int): SDK task UID.
            timeout_in_ms (int | None): SDK既定のtimeout.
            interval_in_ms (int): SDK既定のpoll間隔.
            raise_for_status (bool): 失敗taskでSDK例外を送出するか.

        Returns:
            object: adapterが内容を読まないtask result placeholder.
        """
        _ = (timeout_in_ms, interval_in_ms, raise_for_status)
        self.waited_task_uids.append(task_uid)
        return object()


@pytest.mark.asyncio
async def test_apply_settings_uses_shared_field_declaration() -> None:
    """共有field宣言をMeilisearch settings modelへそのまま送ることを検証する.

    Returns:
        None: settings modelのfield列を検証して完了する.
    """
    client = FakeMeilisearchClient()
    backend = MeilisearchDirectIndexBackend(
        client=_sdk_client(client),
        index_name="direct_sets",
    )

    await backend.apply_settings()

    assert client.index_uid == "direct_sets"
    settings = client.index_handle.settings_updates[0]
    assert settings.searchable_attributes == list(DIRECT_SEARCH_INDEX_DEFINITION.searchable_fields)
    assert settings.filterable_attributes == [
        "status",
        "modes",
        "beatmapset_id",
        "is_active",
    ]
    assert settings.sortable_attributes == list(DIRECT_SEARCH_INDEX_DEFINITION.sortable_fields)
    assert settings.displayed_attributes == ["beatmapset_id", "document_version", "is_active"]
    assert client.waited_task_uids == [1]


@pytest.mark.asyncio
async def test_index_document_sends_declared_public_fields_only() -> None:
    """外部documentが宣言済み公開fieldとactive判定だけを含むことを検証する.

    Returns:
        None: document payloadがstable response sourceを含まないことを検証する.
    """
    client = FakeMeilisearchClient()
    document = BeatmapSetSearchDocument(
        beatmapset_id=123,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        creator="rrtyui",
        artist_unicode="かめりあ",
        title_unicode=None,
        source="",
        tags="speed core",
        difficulty_names="Expert Extra",
        modes=(BeatmapMode.OSU, BeatmapMode.MANIA),
        status=BeatmapRankStatus.RANKED,
        last_update_at=datetime(2026, 8, 9, 12, 34, 56, tzinfo=UTC),
        is_active=True,
        document_version=7,
        updated_at=datetime(2026, 8, 9, 13, 0, 0, tzinfo=UTC),
    )
    backend = MeilisearchDirectIndexBackend(
        client=_sdk_client(client),
        index_name="direct_sets",
    )

    await backend.index_document(document)

    assert client.index_handle.document_batches == [
        (
            [
                {
                    "artist": "Camellia",
                    "artist_unicode": "かめりあ",
                    "beatmapset_id": 123,
                    "creator": "rrtyui",
                    "difficulty_names": "Expert Extra",
                    "document_version": 7,
                    "is_active": True,
                    "last_update_at": "2026-08-09T12:34:56+00:00",
                    "modes": ["osu", "mania"],
                    "source": "",
                    "status": "ranked",
                    "tags": "speed core",
                    "title": "Exit This Earth's Atomosphere",
                    "title_unicode": None,
                }
            ],
            "beatmapset_id",
        )
    ]
    assert client.waited_task_uids == [2]


@pytest.mark.asyncio
async def test_search_returns_candidates_and_passes_declared_filters() -> None:
    """Search backendがMeilisearchへfilter/sort/page条件を渡すことを検証する.

    Returns:
        None: SDK search optionとcandidate変換を検証して完了する.
    """
    client = FakeMeilisearchClient()
    client.index_handle.search_result = SearchResults[dict[str, object]].model_validate(
        {
            "hits": [
                {"beatmapset_id": 41, "_rankingScore": 0.91},
                {"beatmapset_id": 42, "_rankingScore": 0.82},
            ],
            "offset": 2,
            "limit": 2,
            "estimatedTotalHits": 10,
            "processingTimeMs": 1,
            "query": "camellia",
        }
    )
    backend = MeilisearchDirectSearchBackend(
        client=_sdk_client(client),
        index_name="direct_sets",
    )

    result = await backend.search(
        DirectSearchRequest(
            authenticated_user_id=42,
            query_text=" camellia ",
            statuses=(BeatmapRankStatus.RANKED, BeatmapRankStatus.LOVED),
            mode=BeatmapMode.MANIA,
            page=2,
            page_size=1,
        )
    )

    assert result.candidates == (DirectSearchCandidate(beatmapset_id=41, score=0.91),)
    assert result.has_more is True
    assert client.index_handle.search_requests == [
        {
            "query": "camellia",
            "offset": 2,
            "limit": 2,
            "filter": (
                "is_active = true AND (status = ranked OR status = loved) AND modes = mania"
            ),
            "sort": None,
            "attributes_to_retrieve": ["beatmapset_id"],
            "show_ranking_score": True,
        }
    ]


@pytest.mark.asyncio
async def test_validate_reads_health_and_settings_without_writing_settings() -> None:
    """Search backend validationがread-onlyで完了することを検証する.

    Returns:
        None: health/settings確認だけを行いsettings taskを発行しないことを確認する.
    """
    client = FakeMeilisearchClient()
    backend = MeilisearchDirectSearchBackend(
        client=_sdk_client(client),
        index_name="direct_sets",
    )

    await backend.validate()

    assert client.health_calls == 1
    assert client.index_handle.settings_updates == []
    assert client.waited_task_uids == []


@pytest.mark.asyncio
async def test_validate_rejects_missing_required_meilisearch_settings() -> None:
    """Validateがactive filterに必要なsettings不足を拒否することを検証する.

    Returns:
        None: settings不足がstartup errorになることを確認して完了する.
    """
    client = FakeMeilisearchClient()
    client.index_handle.settings = MeilisearchSettings(
        searchable_attributes=list(DIRECT_SEARCH_INDEX_DEFINITION.searchable_fields),
        filterable_attributes=["status", "modes", "beatmapset_id"],
        sortable_attributes=list(DIRECT_SEARCH_INDEX_DEFINITION.sortable_fields),
        displayed_attributes=["beatmapset_id", "document_version"],
    )
    backend = MeilisearchDirectSearchBackend(
        client=_sdk_client(client),
        index_name="direct_sets",
    )

    with pytest.raises(
        MeilisearchDirectSearchBackendUnavailableError,
        match=r"filterableAttributes\.is_active",
    ):
        await backend.validate()
    assert client.index_handle.settings_updates == []


@pytest.mark.asyncio
async def test_index_failure_raises_sanitized_error_for_retry_state() -> None:
    """外部index失敗をretry状態へ記録可能なsanitized errorへ変換する.

    Returns:
        None: 例外messageにsecretやresponse bodyが混入しないことを検証して完了する.
    """
    client = FakeMeilisearchClient()
    client.index_handle.error = MeilisearchError("backend test-access-key stacktrace")
    document = BeatmapSetSearchDocument(
        beatmapset_id=123,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        creator="rrtyui",
        artist_unicode=None,
        title_unicode=None,
        source="",
        tags="",
        difficulty_names="Expert",
        modes=(BeatmapMode.OSU,),
        status=BeatmapRankStatus.RANKED,
        last_update_at=None,
        is_active=True,
        document_version=7,
        updated_at=datetime(2026, 8, 9, 13, 0, 0, tzinfo=UTC),
    )
    backend = MeilisearchDirectIndexBackend(
        client=_sdk_client(client),
        index_name="direct_sets",
    )

    with pytest.raises(MeilisearchDirectIndexError) as exc_info:
        await backend.index_document(document)

    assert str(exc_info.value) == "meilisearch document indexing failed"
    assert exc_info.value.beatmapset_id == 123
    assert exc_info.value.document_version == 7
    assert "test-access-key" not in str(exc_info.value)
    assert "stacktrace" not in str(exc_info.value)


def _valid_settings() -> MeilisearchSettings:
    """検索backendが必要とするsettingsを返す.

    Returns:
        MeilisearchSettings: 全必須fieldを含むsettings.
    """
    return MeilisearchSettings(
        searchable_attributes=list(DIRECT_SEARCH_INDEX_DEFINITION.searchable_fields),
        filterable_attributes=["status", "modes", "beatmapset_id", "is_active"],
        sortable_attributes=list(DIRECT_SEARCH_INDEX_DEFINITION.sortable_fields),
        displayed_attributes=["beatmapset_id", "document_version", "is_active"],
    )


def _sdk_client(client: FakeMeilisearchClient) -> MeilisearchAsyncClient:
    """Fake clientをproduction constructorへ渡すためSDK client型へcastする.

    Args:
        client (FakeMeilisearchClient): Meilisearch SDK client fake.

    Returns:
        MeilisearchAsyncClient: test用に型を合わせたfake client.
    """
    return cast("MeilisearchAsyncClient", cast("object", client))
