"""Bancho HTTP endpoint boundary."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Protocol

from starlette.responses import Response

from osu_server.transports.bancho.protocol import PROTOCOL_VERSION
from osu_server.transports.bancho.workflows import (
    LoginWorkflowInput,
    LoginWorkflowResult,
    PollingWorkflowInput,
    PollingWorkflowResult,
)

if TYPE_CHECKING:
    from starlette.requests import Request


class _LoginWorkflow(Protocol):
    """Login workflow dependency accepted by BanchoEndpoint."""

    async def execute(self, workflow_input: LoginWorkflowInput) -> LoginWorkflowResult:
        """Execute login workflow."""
        ...


class _PollingWorkflow(Protocol):
    """Polling workflow dependency accepted by BanchoEndpoint."""

    async def execute(self, workflow_input: PollingWorkflowInput) -> PollingWorkflowResult:
        """Execute polling workflow."""
        ...


class BanchoEndpoint:
    """Starlette-facing stable bancho POST / endpoint."""

    _login_workflow: _LoginWorkflow
    _polling_workflow: _PollingWorkflow

    def __init__(
        self,
        *,
        login_workflow: _LoginWorkflow,
        polling_workflow: _PollingWorkflow,
    ) -> None:
        self._login_workflow = login_workflow
        self._polling_workflow = polling_workflow

    async def __call__(self, request: Request) -> Response:
        """Map the stable bancho HTTP request to the selected workflow."""
        body = await request.body()

        if "osu-token" in request.headers:
            result = await self._polling_workflow.execute(
                PollingWorkflowInput(
                    token=request.headers["osu-token"],
                    body=body,
                )
            )
            return Response(content=result.content)

        result = await self._login_workflow.execute(
            LoginWorkflowInput(
                body=body,
                headers=request.headers,
            )
        )
        cho_token = result.cho_token if result.cho_token is not None else secrets.token_urlsafe(32)
        return Response(
            content=result.content,
            headers={
                "cho-token": cho_token,
                "cho-protocol": str(PROTOCOL_VERSION),
            },
        )
