"""beatmap mirror source 用 HTTP client と error 分類を実装します."""

from __future__ import annotations

import re
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import httpx
import structlog

from osu_server.domain.beatmaps import (
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
)
from osu_server.infrastructure.http.interfaces import HttpFetchResult

if TYPE_CHECKING:
    from collections.abc import Mapping

    from osu_server.infrastructure.http.interfaces import BeatmapHttpTransport

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_CONTENT_DISPOSITION_FILENAME = re.compile(
    r'filename\s*=\s*"([^"]*)"',
    re.IGNORECASE,
)

_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)

_TEMPORARY_STATUSES: frozenset[int] = frozenset(
    {HTTPStatus.TOO_MANY_REQUESTS} | set(range(500, 600))
)


def _category_for_status(status_code: int) -> BeatmapSourceErrorCategory:
    """HTTP status code を beatmap source error category へ対応付けます.

    Args:
        status_code (int): 分類対象の HTTP response status code です.

    Returns:
        BeatmapSourceErrorCategory: retry,認証,not found,invalid response を表す分類です.
    """
    if status_code == HTTPStatus.TOO_MANY_REQUESTS:
        return BeatmapSourceErrorCategory.RATE_LIMITED
    if status_code in _TEMPORARY_STATUSES:
        return BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE
    if status_code == HTTPStatus.UNAUTHORIZED:
        return BeatmapSourceErrorCategory.UNAUTHORIZED
    if status_code == HTTPStatus.NOT_FOUND:
        return BeatmapSourceErrorCategory.NOT_FOUND
    return BeatmapSourceErrorCategory.INVALID_RESPONSE


def _error_from_response(
    response: httpx.Response,
    *,
    source: str,
    lookup_key: str,
) -> BeatmapSourceError:
    """HTTP error response から分類済み BeatmapSourceError を構築します.

    Args:
        response (httpx.Response): error status を持つ HTTP response です.
        source (str): error と log に記録する beatmap source label です.
        lookup_key (str): error と log に記録する検索 key です.

    Returns:
        BeatmapSourceError: status code と request context を保持する source error です.

    Notes:
        rate limit response の場合だけ beatmap ID を抽出できれば構造化 log に追加します.
    """
    category = _category_for_status(response.status_code)

    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        log_fields: dict[str, object] = {"source": source, "lookup_key": lookup_key}
        beatmap_id = _beatmap_id_from_lookup_key(lookup_key)
        if beatmap_id is not None:
            log_fields["beatmap_id"] = beatmap_id
        logger.warning("beatmap_source_rate_limited", **log_fields)

    return BeatmapSourceError(
        category=category,
        source=source,
        lookup_key=lookup_key,
        message=f"HTTP {response.status_code} from {source} for {lookup_key}",
    )


def _beatmap_id_from_lookup_key(lookup_key: str) -> int | None:
    """beatmap_id lookup key から整数 ID を安全に抽出します.

    Args:
        lookup_key (str): ``beatmap_id=<integer>`` 形式を期待する検索 key です.

    Returns:
        int | None: 形式と整数変換が有効な beatmap ID,または抽出不能時は None です.
    """
    prefix = "beatmap_id="
    if not lookup_key.startswith(prefix):
        return None

    raw_beatmap_id = lookup_key.removeprefix(prefix)
    try:
        return int(raw_beatmap_id)
    except ValueError:
        return None


def _error_from_exception(
    exc: Exception,
    *,
    source: str,
    lookup_key: str,
    category: BeatmapSourceErrorCategory,
) -> BeatmapSourceError:
    """HTTP transport 例外から分類済み BeatmapSourceError を構築します.

    Args:
        exc (Exception): HTTP transport が送出した元の例外です.
        source (str): error に記録する beatmap source label です.
        lookup_key (str): error に記録する検索 key です.
        category (BeatmapSourceErrorCategory): 呼び出し元が確定した error 分類です.

    Returns:
        BeatmapSourceError: 元例外と request context を保持する source error です.
    """
    return BeatmapSourceError(
        category=category,
        source=source,
        lookup_key=lookup_key,
        message=f"{type(exc).__name__} from {source} for {lookup_key}: {exc}",
        original_error=exc,
    )


def _extract_filename(headers: Mapping[str, str]) -> str | None:
    """Content-Disposition header から二重引用符付き filename を抽出します.

    Args:
        headers (Mapping[str, str]): response header の大文字小文字を保持する mapping です.

    Returns:
        str | None: filename parameter の値,または header と形式がない場合は None です.
    """
    disposition = headers.get("Content-Disposition")
    if disposition is None:
        return None
    match = _CONTENT_DISPOSITION_FILENAME.search(disposition)
    return match.group(1) if match else None


def is_permanent_error(error: BeatmapSourceError) -> bool:
    """HTTP beatmap source error が再試行で解消しないか判定します.

    Args:
        error (BeatmapSourceError): 分類済みの beatmap source error です.

    Returns:
        bool: NOT_FOUND または UNAUTHORIZED の場合は True,それ以外は False です.
    """
    return error.category in {
        BeatmapSourceErrorCategory.NOT_FOUND,
        BeatmapSourceErrorCategory.UNAUTHORIZED,
    }


class BeatmapHttpClient:
    """beatmap mirror source から file と JSON を取得する HTTP client です.

    Attributes:
        _client (httpx.AsyncClient | None): 注入済み,または初回利用時に生成する HTTP client です.
    """

    _client: httpx.AsyncClient | None

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        """任意の注入済み HTTP client で client adapter を初期化します.

        Args:
            client (httpx.AsyncClient | None): 再利用する HTTP client です. None の場合は
                初回 request 時に生成します.
        """
        self._client = client

    def _get_client(self) -> httpx.AsyncClient:
        """注入済みまたは遅延生成した HTTP client を返します.

        Returns:
            httpx.AsyncClient: request を実行する再利用可能な HTTP client です.
        """
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    def get_client(self) -> BeatmapHttpTransport:
        """認証付き request 等に利用する低水準 transport を返します.

        Returns:
            BeatmapHttpTransport: この adapter が管理する HTTP transport です.
        """
        return self._get_client()

    async def fetch(
        self,
        url: str,
        *,
        source: str,
        lookup_key: str,
        headers: Mapping[str, str] | None = None,
    ) -> HttpFetchResult:
        """URL から beatmap source の byte 列を取得します.

        Args:
            url (str): 取得対象 URL です.
            source (str): error と log に使う取得元 label です.
            lookup_key (str): error と log に使う検索 key です.
            headers (Mapping[str, str] | None): requestへ追加するHTTP headerです.

        Returns:
            HttpFetchResult: 取得した response body と任意の filename metadata です.

        Raises:
            BeatmapSourceError: HTTP error,timeout,または接続 failure を分類した場合.
        """
        client = self._get_client()

        try:
            response = await client.get(url, follow_redirects=True, headers=headers)
        except _TRANSIENT_EXCEPTIONS as exc:
            category = (
                BeatmapSourceErrorCategory.TIMEOUT
                if isinstance(exc, httpx.TimeoutException)
                else BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE
            )
            raise _error_from_exception(
                exc,
                source=source,
                lookup_key=lookup_key,
                category=category,
            ) from exc

        if response.status_code == HTTPStatus.OK:
            filename = _extract_filename(response.headers)
            return HttpFetchResult(content=response.content, filename=filename)

        raise _error_from_response(response, source=source, lookup_key=lookup_key)

    async def fetch_json(
        self,
        url: str,
        *,
        source: str,
        lookup_key: str,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, object] | list[object]:
        """URL から JSON を取得し,object または array として返します.

        Args:
            url (str): 取得対象 URL です.
            source (str): error と log に使う取得元 label です.
            lookup_key (str): error と log に使う検索 key です.
            headers (Mapping[str, str] | None): requestへ追加するHTTP headerです.

        Returns:
            dict[str, object] | list[object]: JSON object または array です.

        Raises:
            BeatmapSourceError: HTTP error,接続失敗,JSON decode failure,または top-level JSON
                primitive の場合に分類済み error を送出します.

        Notes:
            JSON primitive は contract 違反のため INVALID_RESPONSE として拒否します.
        """
        result = await self.fetch(url, source=source, lookup_key=lookup_key, headers=headers)
        try:
            parsed = cast("object", httpx.Response(200, content=result.content).json())
        except Exception as exc:
            raise BeatmapSourceError(
                category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
                source=source,
                lookup_key=lookup_key,
                message=f"JSON decode error from {source}: {exc}",
                original_error=exc,
            ) from exc

        if isinstance(parsed, dict):
            return cast("dict[str, object]", parsed)
        if isinstance(parsed, list):
            return cast("list[object]", parsed)
        actual = type(parsed).__name__
        raise BeatmapSourceError(
            category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
            source=source,
            lookup_key=lookup_key,
            message=f"Expected JSON object or array from {source}, got {actual}",
        )
