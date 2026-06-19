"""Starlette Request を作る test support helper。"""

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
    """ASGI scope の細部を隠して Starlette Request を組み立てる。"""

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
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)
