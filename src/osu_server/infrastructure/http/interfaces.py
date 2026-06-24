"""HTTP infrastructure の公開 interface です."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(slots=True)
class HttpFetchResult:
    """HTTP から取得したバイト列と付随 metadata です.

    Attributes:
        content: 取得した response body です.
        filename: Content-Disposition 等から判定したファイル名です. 未判定の場合は None です.
    """

    content: bytes
    filename: str | None


class HttpResponse(Protocol):
    """HTTP response のうち service が参照する最小 interface です."""

    @property
    def status_code(self) -> int:
        """HTTP status code を返します.

        Returns:
            HTTP status code です.

        Raises:
            送出しません.
        """
        ...

    def json(self) -> object:
        """response body を JSON として decode します.

        Returns:
            JSON decode 後の Python object です.

        Raises:
            body が JSON として解釈できない場合は実装側の例外を送出します.
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
            url: request 先 URL です.
            headers: request header です.
            follow_redirects: redirect を追跡するかどうかです.

        Returns:
            HTTP response です.

        Raises:
            network error や timeout は実装側の例外を送出します.
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
            url: request 先 URL です.
            data: form body として送る key-value です.

        Returns:
            HTTP response です.

        Raises:
            network error や timeout は実装側の例外を送出します.
        """
        ...


class BeatmapHttpClient(Protocol):
    """Beatmap metadata/file provider が利用する HTTP client port です."""

    def get_client(self) -> BeatmapHttpTransport:
        """認証付き request などに使う低水準 HTTP transport を返します.

        Returns:
            HTTP request を実行する transport です.

        Raises:
            送出しません.
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
            url: 取得対象 URL です.
            source: error と log に使う取得元 label です.
            lookup_key: error と log に使う検索 key です.

        Returns:
            取得した body と filename metadata です.

        Raises:
            取得失敗時は BeatmapSourceError 等の実装側例外を送出します.
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
            url: 取得対象 URL です.
            source: error と log に使う取得元 label です.
            lookup_key: error と log に使う検索 key です.

        Returns:
            JSON object または array です.

        Raises:
            取得失敗または JSON decode 失敗時は BeatmapSourceError 等の実装側例外を送出します.
        """
        ...


__all__ = [
    "BeatmapHttpClient",
    "BeatmapHttpTransport",
    "HttpFetchResult",
    "HttpResponse",
]
