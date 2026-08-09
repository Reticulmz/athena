"""Meilisearch向けosu!direct external index adapterを提供するmodule."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from urllib.parse import quote

import httpx

from osu_server.infrastructure.search.direct_index_definition import (
    DIRECT_SEARCH_INDEX_DEFINITION,
    SearchIndexDefinition,
)

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps.direct import BeatmapSetSearchDocument

_BACKEND_NAME: Final = "meilisearch"
_HTTP_SUCCESS_MIN: Final = 200
_HTTP_SUCCESS_MAX: Final = 300


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


class MeilisearchDirectIndexBackend:
    """Meilisearchへosu!direct projection documentを同期するadapter.

    Attributes:
        _http_client (httpx.AsyncClient): lifecycleを呼び出し側が所有するHTTP client.
        _base_url (str): Meilisearch serverのbase URL.
        _index_name (str): Meilisearch index UID.
        _access_key (str | None): Authorization headerへ設定するaccess key.
        _index_definition (SearchIndexDefinition): settingsとdocument fieldの共有宣言.
    """

    _http_client: httpx.AsyncClient
    _base_url: str
    _index_name: str
    _access_key: str | None
    _index_definition: SearchIndexDefinition

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        base_url: str,
        index_name: str,
        access_key: str | None = None,
        index_definition: SearchIndexDefinition = DIRECT_SEARCH_INDEX_DEFINITION,
    ) -> None:
        """HTTP clientとMeilisearch index設定を保持する.

        Args:
            http_client (httpx.AsyncClient): Meilisearch requestを送るasync HTTP client.
            base_url (str): Meilisearch serverのbase URL.
            index_name (str): osu!direct用Meilisearch index UID.
            access_key (str | None): Meilisearch access key. 未設定ならheaderを送らない.
            index_definition (SearchIndexDefinition): 共有field宣言.

        Raises:
            ValueError: base_urlまたはindex_nameが空の場合.
        """
        if not base_url.strip():
            msg = "base_url must not be empty"
            raise ValueError(msg)
        if not index_name.strip():
            msg = "index_name must not be empty"
            raise ValueError(msg)
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")
        self._index_name = quote(index_name.strip(), safe="")
        self._access_key = access_key
        self._index_definition = index_definition

    async def apply_settings(self) -> None:
        """共有field宣言をMeilisearch settingsへ適用する.

        Returns:
            None: settings更新requestがMeilisearchへ受理されたことを示す.

        Raises:
            MeilisearchDirectIndexError: Meilisearch requestが失敗した場合.
        """
        response = await self._request(
            "PATCH",
            self._settings_url(),
            json={
                "searchableAttributes": list(self._index_definition.searchable_fields),
                "filterableAttributes": list(self._index_definition.filterable_fields),
                "sortableAttributes": list(self._index_definition.sortable_fields),
                "displayedAttributes": list(self._index_definition.displayed_fields),
            },
            failure_context="settings update",
        )
        _ = response

    async def index_document(self, document: BeatmapSetSearchDocument) -> None:
        """Committed projection documentをMeilisearchへ同期する.

        Args:
            document (BeatmapSetSearchDocument): DB commit後に読み直したprojection document.

        Returns:
            None: document更新requestがMeilisearchへ受理されたことを示す.

        Raises:
            MeilisearchDirectIndexError: Meilisearch requestが失敗した場合.
        """
        response = await self._request(
            "PUT",
            self._documents_url(),
            json=[_document_payload(document, self._index_definition)],
            failure_context="document indexing",
            beatmapset_id=document.beatmapset_id,
            document_version=document.document_version,
        )
        _ = response

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: object,
        failure_context: str,
        beatmapset_id: int | None = None,
        document_version: int | None = None,
    ) -> httpx.Response:
        """Meilisearch HTTP requestを送信して失敗をsanitized errorへ変換する.

        Args:
            method (str): HTTP method.
            url (str): request送信先URL.
            json (object): JSON bodyへserializeするpayload.
            failure_context (str): sanitized messageに入れる操作名.
            beatmapset_id (int | None): document更新時のbeatmapset ID.
            document_version (int | None): document更新時のprojection version.

        Returns:
            httpx.Response: 2xxとして受理されたresponse.

        Raises:
            MeilisearchDirectIndexError: HTTP statusまたは通信が失敗した場合.
        """
        try:
            response = await self._http_client.request(
                method,
                url,
                headers=self._headers(),
                json=json,
            )
        except httpx.HTTPError as exc:
            msg = f"{_BACKEND_NAME} {failure_context} request failed"
            raise MeilisearchDirectIndexError(
                msg,
                beatmapset_id=beatmapset_id,
                document_version=document_version,
            ) from exc
        if response.status_code < _HTTP_SUCCESS_MIN or response.status_code >= _HTTP_SUCCESS_MAX:
            msg = f"{_BACKEND_NAME} {failure_context} failed with HTTP {response.status_code}"
            raise MeilisearchDirectIndexError(
                msg,
                beatmapset_id=beatmapset_id,
                document_version=document_version,
            )
        return response

    def _headers(self) -> dict[str, str]:
        """Meilisearch requestへ付けるheaderを返す.

        Returns:
            dict[str, str]: access keyがある場合だけAuthorizationを含むheader.
        """
        if self._access_key:
            return {"Authorization": f"Bearer {self._access_key}"}
        return {}

    def _settings_url(self) -> str:
        """Settings endpointのURLを返す.

        Returns:
            str: Meilisearch settings endpoint URL.
        """
        return f"{self._base_url}/indexes/{self._index_name}/settings"

    def _documents_url(self) -> str:
        """Documents endpointのURLを返す.

        Returns:
            str: primaryKey query付きMeilisearch documents endpoint URL.
        """
        return f"{self._base_url}/indexes/{self._index_name}/documents?primaryKey=beatmapset_id"


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
                *index_definition.filterable_fields,
                *index_definition.sortable_fields,
                *index_definition.displayed_fields,
            )
        )
    )


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
]
