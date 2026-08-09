"""Meilisearch osu!direct adapterのHTTP contractを検証するmodule."""

import json
from datetime import UTC, datetime
from typing import Protocol, cast

import httpx
import pytest

from osu_server.domain.beatmaps.direct import BeatmapSetSearchDocument
from osu_server.domain.beatmaps.models import BeatmapMode, BeatmapRankStatus
from osu_server.infrastructure.search.direct_index_definition import (
    DIRECT_SEARCH_INDEX_DEFINITION,
)
from osu_server.infrastructure.search.meilisearch_direct import (
    MeilisearchDirectIndexBackend,
    MeilisearchDirectIndexError,
)


class CapturedRequest(Protocol):
    """MockTransportで検証するrequestの必要最小限のviewを表す."""

    @property
    def method(self) -> str:
        """HTTP methodを返す.

        Returns:
            str: adapterが送信したHTTP method.
        """
        ...

    @property
    def url(self) -> object:
        """Request URLを返す.

        Returns:
            object: 文字列化してpathとqueryを検証できるURL.
        """
        ...

    @property
    def headers(self) -> httpx.Headers:
        """Request headerを返す.

        Returns:
            httpx.Headers: authorizationを検証するheader集合.
        """
        ...

    @property
    def content(self) -> bytes:
        """Request body bytesを返す.

        Returns:
            bytes: JSON payloadとしてdecodeできるbody.
        """
        ...


@pytest.mark.asyncio
async def test_apply_settings_uses_shared_field_declaration() -> None:
    """共有field宣言をMeilisearch settingsへそのまま送ることを検証する.

    Returns:
        None: settings requestのpath, header, bodyを検証して完了する.
    """
    requests: list[CapturedRequest] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Settings requestを捕捉して成功responseを返す.

        Args:
            request (httpx.Request): adapterが送信したsettings request.

        Returns:
            httpx.Response: Meilisearch task作成成功を表すresponse.
        """
        requests.append(cast("CapturedRequest", cast("object", request)))
        return httpx.Response(202, json={"taskUid": 1}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        backend = MeilisearchDirectIndexBackend(
            http_client=http_client,
            base_url="http://meili.local",
            index_name="direct_sets",
            access_key="test-access-key",
        )

        await backend.apply_settings()

    assert len(requests) == 1
    assert requests[0].method == "PATCH"
    assert str(requests[0].url) == "http://meili.local/indexes/direct_sets/settings"
    assert requests[0].headers["authorization"] == "Bearer test-access-key"
    assert json.loads(requests[0].content) == {
        "searchableAttributes": list(DIRECT_SEARCH_INDEX_DEFINITION.searchable_fields),
        "filterableAttributes": list(DIRECT_SEARCH_INDEX_DEFINITION.filterable_fields),
        "sortableAttributes": list(DIRECT_SEARCH_INDEX_DEFINITION.sortable_fields),
        "displayedAttributes": list(DIRECT_SEARCH_INDEX_DEFINITION.displayed_fields),
    }


@pytest.mark.asyncio
async def test_index_document_sends_declared_public_fields_only() -> None:
    """外部documentが宣言済み公開fieldとversionだけを含むことを検証する.

    Returns:
        None: document requestのpayloadがstable response sourceを含まないことを検証する.
    """
    requests: list[CapturedRequest] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Document requestを捕捉して成功responseを返す.

        Args:
            request (httpx.Request): adapterが送信したdocument indexing request.

        Returns:
            httpx.Response: Meilisearch task作成成功を表すresponse.
        """
        requests.append(cast("CapturedRequest", cast("object", request)))
        return httpx.Response(202, json={"taskUid": 2}, request=request)

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

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        backend = MeilisearchDirectIndexBackend(
            http_client=http_client,
            base_url="http://meili.local/",
            index_name="direct_sets",
        )

        await backend.index_document(document)

    assert len(requests) == 1
    assert requests[0].method == "PUT"
    assert str(requests[0].url) == (
        "http://meili.local/indexes/direct_sets/documents?primaryKey=beatmapset_id"
    )
    assert json.loads(requests[0].content) == [
        {
            "artist": "Camellia",
            "artist_unicode": "かめりあ",
            "beatmapset_id": 123,
            "creator": "rrtyui",
            "difficulty_names": "Expert Extra",
            "document_version": 7,
            "last_update_at": "2026-08-09T12:34:56+00:00",
            "modes": ["osu", "mania"],
            "source": "",
            "status": "ranked",
            "tags": "speed core",
            "title": "Exit This Earth's Atomosphere",
            "title_unicode": None,
        }
    ]


@pytest.mark.asyncio
async def test_index_failure_raises_sanitized_error_for_retry_state() -> None:
    """外部index失敗をretry状態へ記録可能なsanitized errorへ変換する.

    Returns:
        None: 例外messageにsecretやresponse bodyが混入しないことを検証して完了する.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Meilisearch失敗responseを返す.

        Args:
            request (httpx.Request): adapterが送信したdocument indexing request.

        Returns:
            httpx.Response: access keyに似たbodyを持つ失敗response.
        """
        return httpx.Response(
            503,
            text="backend test-access-key stacktrace",
            request=request,
        )

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

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        backend = MeilisearchDirectIndexBackend(
            http_client=http_client,
            base_url="http://meili.local",
            index_name="direct_sets",
            access_key="test-access-key",
        )

        with pytest.raises(MeilisearchDirectIndexError) as exc_info:
            await backend.index_document(document)

    assert str(exc_info.value) == "meilisearch document indexing failed with HTTP 503"
    assert exc_info.value.beatmapset_id == 123
    assert exc_info.value.document_version == 7
    assert "test-access-key" not in str(exc_info.value)
    assert "stacktrace" not in str(exc_info.value)
