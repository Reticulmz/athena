"""Tests for transport endpoint composition."""

from __future__ import annotations

from typing import final

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

from osu_server.composition.endpoints import bancho_endpoint


@final
class _RecordingBanchoEndpoint:
    """Fake BanchoEndpoint for testing composition routing."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, request: Request) -> Response:
        _ = request
        self.called = True
        return Response(content=b"test-response")


@pytest.mark.asyncio
async def test_bancho_endpoint_delegates_to_refactored_endpoint() -> None:
    """bancho_endpoint adapter pulls BanchoEndpoint from app.state."""
    fake_endpoint = _RecordingBanchoEndpoint()

    app = Starlette()
    app.state.bancho_endpoint = fake_endpoint

    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "app": app,
        }
    )

    response = await bancho_endpoint(request)

    assert fake_endpoint.called
    assert response.body == b"test-response"
