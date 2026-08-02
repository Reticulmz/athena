"""Stable Bancho HTTP request を login または polling workflow へ適合させる."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Protocol

from starlette.responses import Response

from osu_server.transports.stable.bancho.protocol import PROTOCOL_VERSION
from osu_server.transports.stable.bancho.workflows import (
    LoginWorkflowInput,
    LoginWorkflowResult,
    PollingWorkflowInput,
    PollingWorkflowResult,
)

if TYPE_CHECKING:
    from starlette.requests import Request


class _LoginWorkflow(Protocol):
    """BanchoEndpoint が受け取る login workflow の contract を表す."""

    async def execute(self, workflow_input: LoginWorkflowInput) -> LoginWorkflowResult:
        """指定した login workflow input を処理して response contract を返す.

        Args:
            workflow_input (LoginWorkflowInput): HTTP boundary から変換した login 入力.

        Returns:
            LoginWorkflowResult: response bytes と cho-token の contract.
        """
        ...


class _PollingWorkflow(Protocol):
    """BanchoEndpoint が受け取る polling workflow の contract を表す."""

    async def execute(self, workflow_input: PollingWorkflowInput) -> PollingWorkflowResult:
        """指定した polling workflow input を処理して response contract を返す.

        Args:
            workflow_input (PollingWorkflowInput): HTTP boundary から変換した polling 入力.

        Returns:
            PollingWorkflowResult: client へ返す S2C response bytes の contract.
        """
        ...


class BanchoEndpoint:
    """Stable Bancho の POST / request を workflow へ委譲する.

    Attributes:
        _login_workflow (_LoginWorkflow): osu-token がない request を処理する workflow.
        _polling_workflow (_PollingWorkflow): osu-token がある request を処理する workflow.
    """

    _login_workflow: _LoginWorkflow
    _polling_workflow: _PollingWorkflow

    def __init__(
        self,
        *,
        login_workflow: _LoginWorkflow,
        polling_workflow: _PollingWorkflow,
    ) -> None:
        """HTTP boundary が委譲する login と polling workflow を設定する.

        Args:
            login_workflow (_LoginWorkflow): 初回 login request を処理する workflow.
            polling_workflow (_PollingWorkflow): 認証後 polling request を処理する workflow.
        """
        self._login_workflow = login_workflow
        self._polling_workflow = polling_workflow

    async def __call__(self, request: Request) -> Response:
        """Stable Bancho HTTP request を選択した workflow の response へ変換する.

        Args:
            request (Request): stable client が送信した POST request.

        Returns:
            Response: polling では S2C bytes だけを持ち, login では Bancho header も持つ response.

        Notes:
            osu-token header が存在すれば値が空でも polling を選ぶ. login response の cho-token が
            None の場合は endpoint が random token を発行し cho-protocol も常に設定する.
        """
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
