"""HTTP infrastructure が公開する最小限の interface を定義します."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(slots=True)
class HttpFetchResult:
    """HTTP から取得した byte 列と付随 metadata です.

    Attributes:
        content (bytes): 取得した response body です.
        filename (str | None): Content-Disposition 等から判定したファイル名です. 未判定の場合は
            None です.
    """

    content: bytes
    filename: str | None


class HttpResponse(Protocol):
    """利用側 service が参照する HTTP response の最小 interface です."""

    @property
    def status_code(self) -> int:
        """HTTP status code を返します.

        Returns:
            int: HTTP status code です.
        """
        ...

    def json(self) -> object:
        """Response body を JSON として decode します.

        Returns:
            object: JSON decode 後の Python object です.

        Notes:
            JSON decode failure の具体的な例外型は response 実装が定義します.
        """
        ...


class BeatmapHttpTransport(Protocol):
    """Beatmap HTTP client が公開する低水準 HTTP transport です."""

    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> HttpResponse:
        """HTTP GET を実行します.

        Args:
            url (str): request 先 URL です.
            headers (Mapping[str, str] | None): request header です.
            follow_redirects (bool): redirect を追跡するかどうかです.

        Returns:
            HttpResponse: HTTP request の response です.

        Notes:
            network error と timeout の具体的な例外型は transport 実装が定義します.
        """
        ...

    async def post(
        self,
        url: str,
        *,
        data: Mapping[str, str],
    ) -> HttpResponse:
        """HTTP POST を実行します.

        Args:
            url (str): request 先 URL です.
            data (Mapping[str, str]): form body として送る key-value です.

        Returns:
            HttpResponse: HTTP request の response です.

        Notes:
            network error と timeout の具体的な例外型は transport 実装が定義します.
        """
        ...


class BeatmapHttpClient(Protocol):
    """Beatmap metadata/file provider が利用する HTTP client port です."""

    def get_client(self) -> BeatmapHttpTransport:
        """認証付き request などに使う低水準 HTTP transport を返します.

        Returns:
            BeatmapHttpTransport: HTTP request を実行する transport です.
        """
        ...

    async def fetch(
        self,
        url: str,
        *,
        source: str,
        lookup_key: str,
    ) -> HttpFetchResult:
        """URL からバイト列を取得します.

        Args:
            url (str): 取得対象 URL です.
            source (str): error と log に使う取得元 label です.
            lookup_key (str): error と log に使う検索 key です.

        Returns:
            HttpFetchResult: 取得した body と filename metadata です.

        Raises:
            BeatmapSourceError: HTTP error,timeout,または connection failure を分類して
                送出する場合.
        """
        ...

    async def fetch_json(
        self,
        url: str,
        *,
        source: str,
        lookup_key: str,
    ) -> dict[str, object] | list[object]:
        """URL から JSON を取得します.

        Args:
            url (str): 取得対象 URL です.
            source (str): error と log に使う取得元 label です.
            lookup_key (str): error と log に使う検索 key です.

        Returns:
            dict[str, object] | list[object]: JSON object または array です.

        Raises:
            BeatmapSourceError: HTTP,接続,JSON decode の失敗,または top-level JSON primitive
                の場合.
        """
        ...


__all__ = [
    "BeatmapHttpClient",
    "BeatmapHttpTransport",
    "HttpFetchResult",
    "HttpResponse",
]
