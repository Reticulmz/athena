"""Stable login前のbancho_connect到達確認endpointを提供する.

usernameとpassword md5は後続のbancho login POSTで検証するため, このendpointは
接続可能であることだけを空responseで返す.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import Response

if TYPE_CHECKING:
    from starlette.requests import Request


async def bancho_connect_endpoint(request: Request) -> Response:
    """Stable clientのbancho_connect requestへ空responseを返す.

    Args:
        request (Request): username, password md5, versionを含むGET request.

    Returns:
        Response: 認証を行わず空bodyで返すHTTP 200 response.

    Notes:
        query parameterは互換性のため読み取るだけで, credential検証はbancho login
        POST flowへ委譲する.
    """
    _username = request.query_params.get("u")
    _password_md5 = request.query_params.get("h")
    _osu_version = request.query_params.get("v")
    _active_endpoint = request.query_params.get("fail")
    # Future: validate credentials here as lets does.
    # Currently delegated to the bancho login POST flow.
    return Response(b"")
