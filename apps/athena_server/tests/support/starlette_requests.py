"""Starlette Requestを作るtest support helperを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from starlette.requests import Request

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from starlette.types import Message, Scope

type HeaderPair = tuple[bytes, bytes]


def make_starlette_request(
    *,
    method: str = "GET",
    path: str = "/",
    query_params: Mapping[str, str] | None = None,
    query_string: bytes = b"",
    headers: Iterable[HeaderPair] = (),
    body: bytes | None = None,
    app: object | None = None,
) -> Request:
    """ASGI scopeの細部を隠してStarlette Requestを組み立てる.

    Args:
        method (str): requestのHTTP method.
        path (str): request targetのpath.
        query_params (Mapping[str, str] | None): URL encodeするquery parameter.
        query_string (bytes): query_params未指定時にそのまま使うraw query string.
        headers (Iterable[HeaderPair]): ASGI scopeへ設定するbyte header pair.
        body (bytes | None): request body. Noneの場合はreceive callableを設定しない.
        app (object | None): scopeへ任意で設定するASGI application object.

    Returns:
        Request: 指定scopeとbody delivery contractを持つStarlette request.
    """
    if query_params is not None:
        query_string = urlencode(query_params).encode()

    scope: Scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": list(headers),
        "query_string": query_string,
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
    }
    if app is not None:
        scope["app"] = app

    if body is None:
        return Request(scope)

    received = False

    async def receive() -> Message:
        """1回限りのrequest bodyをASGI messageとして供給する.

        Returns:
            Message: 初回はbodyを持つhttp.request, 2回目以降はhttp.disconnect.
        """
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)
