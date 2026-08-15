"""Tests for transport endpoint composition."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

import pytest
from starlette.applications import Starlette
from starlette.responses import Response
from tests.support.starlette_requests import make_starlette_request

from osu_server.composition.endpoints import (
    bancho_endpoint,
    direct_point_lookup_endpoint,
    direct_search_endpoint,
    replay_download_endpoint,
)

if TYPE_CHECKING:
    from starlette.requests import Request


@final
class _RecordingBanchoEndpoint:
    """Composition routing の呼出しを記録する Bancho endpoint fake.

    Attributes:
        called (bool): endpoint が request を受け取ったか.
    """

    def __init__(self) -> None:
        """未呼出し状態の endpoint fake を初期化する."""
        self.called = False

    async def __call__(self, request: Request) -> Response:
        """Request を記録して固定 Bancho response を返す.

        Args:
            request (Request): adapter から渡される Bancho request.

        Returns:
            Response: 固定 test response.
        """
        _ = request
        self.called = True
        return Response(content=b"test-response")


@final
class _RecordingReplayDownloadHandler:
    """Composition routing の呼出しを記録する replay download handler fake.

    Attributes:
        called (bool): handler が request を受け取ったか.
    """

    def __init__(self) -> None:
        """未呼出し状態の replay handler fake を初期化する."""
        self.called = False

    async def __call__(self, request: Request) -> Response:
        """Request を記録して固定 replay response を返す.

        Args:
            request (Request): adapter から渡される replay request.

        Returns:
            Response: 固定 test response.
        """
        _ = request
        self.called = True
        return Response(content=b"replay-response")


@final
class _RecordingDirectHandler:
    """Composition routing の呼出しを記録する direct handler fake.

    Attributes:
        called (bool): handler が request を受け取ったか.
        content (bytes): adapter 経由で返す固定 response body.
    """

    def __init__(self, content: bytes) -> None:
        """未呼出し状態の direct handler fake を初期化する.

        Args:
            content (bytes): fake handler が返す response body.
        """
        self.called = False
        self.content = content

    async def __call__(self, request: Request) -> Response:
        """Request を記録して固定 direct response を返す.

        Args:
            request (Request): adapter から渡される direct request.

        Returns:
            Response: 固定 test response.
        """
        _ = request
        self.called = True
        return Response(content=self.content)


@pytest.mark.asyncio
async def test_bancho_endpoint_delegates_to_refactored_endpoint() -> None:
    """Bancho endpoint adapter が app.state の handler へ request を委譲する契約を検証する.

    Returns:
        None: fake handler の呼出しと response body を検証して完了する.
    """
    fake_endpoint = _RecordingBanchoEndpoint()

    app = Starlette()
    app.state.bancho_endpoint = fake_endpoint

    request = make_starlette_request(method="POST", app=app)

    response = await bancho_endpoint(request)

    assert fake_endpoint.called
    assert response.body == b"test-response"


@pytest.mark.asyncio
async def test_replay_download_endpoint_delegates_to_stable_handler() -> None:
    """Replay download adapter が app.state の stable handler へ request を委譲する契約を検証する.

    Returns:
        None: fake handler の呼出しと response body を検証して完了する.
    """
    fake_handler = _RecordingReplayDownloadHandler()

    app = Starlette()
    app.state.replay_download_handler = fake_handler

    request = make_starlette_request(
        method="GET",
        path="/web/osu-getreplay.php",
        app=app,
    )

    response = await replay_download_endpoint(request)

    assert fake_handler.called
    assert response.body == b"replay-response"


@pytest.mark.asyncio
async def test_direct_search_endpoint_delegates_to_stable_handler() -> None:
    """Direct search adapter が app.state の stable handler へ request を委譲する契約を検証する.

    Returns:
        None: fake handler の呼出しと response body を検証して完了する.
    """
    fake_handler = _RecordingDirectHandler(b"0")

    app = Starlette()
    app.state.direct_search_handler = fake_handler

    request = make_starlette_request(
        method="GET",
        path="/web/osu-search.php",
        app=app,
    )

    response = await direct_search_endpoint(request)

    assert fake_handler.called
    assert response.body == b"0"


@pytest.mark.asyncio
async def test_direct_point_lookup_endpoint_delegates_to_stable_handler() -> None:
    """Direct point lookup adapter が app.state の stable handler へ委譲する契約を検証する.

    Returns:
        None: fake handler の呼出しと response body を検証して完了する.
    """
    fake_handler = _RecordingDirectHandler(b"lookup")

    app = Starlette()
    app.state.direct_point_lookup_handler = fake_handler

    request = make_starlette_request(
        method="GET",
        path="/web/osu-search-set.php",
        app=app,
    )

    response = await direct_point_lookup_endpoint(request)

    assert fake_handler.called
    assert response.body == b"lookup"
