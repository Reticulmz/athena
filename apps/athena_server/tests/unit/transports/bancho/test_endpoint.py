"""BanchoEndpoint HTTP boundary の login と polling workflow routing を検証する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
from osu_server.transports.stable.bancho.workflows import (
    LoginWorkflowInput,
    LoginWorkflowResult,
    PollingWorkflowInput,
    PollingWorkflowResult,
)


@dataclass(slots=True, frozen=True)
class _WorkflowCalls:
    """test fake workflow が受け取った login と polling call 数を表す.

    Attributes:
        login_count (int): login workflow が受け取った call 数.
        polling_count (int): polling workflow が受け取った call 数.
    """

    login_count: int
    polling_count: int


@final
class _RecordingLoginWorkflow:
    """endpoint から渡された LoginWorkflowInput を記録する login workflow fake を表す.

    Attributes:
        _result (LoginWorkflowResult): execute ごとに返す固定 login workflow result.
        inputs (list[LoginWorkflowInput]): endpoint から受け取った login input の記録順 list.
    """

    _result: LoginWorkflowResult
    inputs: list[LoginWorkflowInput]

    def __init__(self, result: LoginWorkflowResult) -> None:
        """固定 result を返す login workflow fake を初期化する.

        Args:
            result (LoginWorkflowResult): execute ごとに返す固定 login workflow result.
        """
        self._result = result
        self.inputs = []

    async def execute(self, workflow_input: LoginWorkflowInput) -> LoginWorkflowResult:
        """Login input を記録して固定 result を返す.

        Args:
            workflow_input (LoginWorkflowInput): endpoint が mapping した login input.

        Returns:
            LoginWorkflowResult: constructor で設定した固定 result.
        """
        self.inputs.append(workflow_input)
        return self._result


@final
class _RecordingPollingWorkflow:
    """endpoint から渡された PollingWorkflowInput を記録する polling workflow fake を表す.

    Attributes:
        _result (PollingWorkflowResult): execute ごとに返す固定 polling workflow result.
        inputs (list[PollingWorkflowInput]): endpoint から受け取った polling input の記録順 list.
    """

    _result: PollingWorkflowResult
    inputs: list[PollingWorkflowInput]

    def __init__(self, result: PollingWorkflowResult) -> None:
        """固定 result を返す polling workflow fake を初期化する.

        Args:
            result (PollingWorkflowResult): execute ごとに返す固定 polling workflow result.
        """
        self._result = result
        self.inputs = []

    async def execute(self, workflow_input: PollingWorkflowInput) -> PollingWorkflowResult:
        """Polling input を記録して固定 result を返す.

        Args:
            workflow_input (PollingWorkflowInput): endpoint が mapping した polling input.

        Returns:
            PollingWorkflowResult: constructor で設定した固定 result.
        """
        self.inputs.append(workflow_input)
        return self._result


def _make_client(
    *,
    login_result: LoginWorkflowResult | None = None,
    polling_result: PollingWorkflowResult | None = None,
) -> tuple[TestClient, _RecordingLoginWorkflow, _RecordingPollingWorkflow]:
    """Recording fake workflow を持つ BanchoEndpoint test client を構築する.

    Args:
        login_result (LoginWorkflowResult | None): login fake の固定 result.
            None なら default result を使う.
        polling_result (PollingWorkflowResult | None): polling fake の固定 result.
            None なら default result を使う.

    Returns:
        tuple[TestClient, _RecordingLoginWorkflow, _RecordingPollingWorkflow]: HTTP test client と
            input を検査する 2つの recording fake.
    """
    if login_result is None:
        login_result = LoginWorkflowResult(
            content=b"login-bytes",
            cho_token=None,
        )
    if polling_result is None:
        polling_result = PollingWorkflowResult(content=b"polling-bytes")

    login_workflow = _RecordingLoginWorkflow(login_result)
    polling_workflow = _RecordingPollingWorkflow(polling_result)
    endpoint = BanchoEndpoint(
        login_workflow=login_workflow,
        polling_workflow=polling_workflow,
    )
    app = Starlette(routes=[Route("/", endpoint.__call__, methods=["POST"])])
    return TestClient(app), login_workflow, polling_workflow


def _calls(
    login_workflow: _RecordingLoginWorkflow,
    polling_workflow: _RecordingPollingWorkflow,
) -> _WorkflowCalls:
    """Recording fake workflow の execute call 数を snapshot にまとめる.

    Args:
        login_workflow (_RecordingLoginWorkflow): login input を記録する fake workflow.
        polling_workflow (_RecordingPollingWorkflow): polling input を記録する fake workflow.

    Returns:
        _WorkflowCalls: 両 workflow が記録した input 数を持つ immutable snapshot.
    """
    return _WorkflowCalls(
        login_count=len(login_workflow.inputs),
        polling_count=len(polling_workflow.inputs),
    )


class TestBanchoEndpoint:
    """BanchoEndpoint が HTTP request を workflow input と response に変換することを検証する."""

    def test_without_osu_token_header_delegates_to_login_workflow(self) -> None:
        """osu-token がない request が login workflow に body と headers を渡すことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        client, login_workflow, polling_workflow = _make_client()

        response = client.post("/", content=b"raw-login", headers={"x-test": "1"})

        assert response.content == b"login-bytes"
        assert "cho-token" in response.headers
        assert "cho-protocol" in response.headers
        assert _calls(login_workflow, polling_workflow) == _WorkflowCalls(
            login_count=1,
            polling_count=0,
        )
        workflow_input = login_workflow.inputs[0]
        assert workflow_input.body == b"raw-login"
        assert workflow_input.headers["x-test"] == "1"

    def test_login_result_token_is_mapped_to_cho_token_header(self) -> None:
        """Login result cho token が response cho-token header に mapping されることを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        client, login_workflow, polling_workflow = _make_client(
            login_result=LoginWorkflowResult(
                content=b"successful-login",
                cho_token="issued-token",
            )
        )

        response = client.post("/", content=b"raw-login")

        assert response.content == b"successful-login"
        assert response.headers["cho-token"] == "issued-token"
        assert response.headers["cho-protocol"] == "19"
        assert _calls(login_workflow, polling_workflow) == _WorkflowCalls(
            login_count=1,
            polling_count=0,
        )

    def test_osu_token_header_presence_delegates_to_polling_workflow(self) -> None:
        """osu-token がある request が polling workflow に token と body を渡すことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        client, login_workflow, polling_workflow = _make_client()

        response = client.post(
            "/",
            content=b"raw-c2s",
            headers={"osu-token": "poll-token"},
        )

        assert response.content == b"polling-bytes"
        assert "cho-token" not in response.headers
        assert _calls(login_workflow, polling_workflow) == _WorkflowCalls(
            login_count=0,
            polling_count=1,
        )
        workflow_input = polling_workflow.inputs[0]
        assert workflow_input.token == "poll-token"
        assert workflow_input.body == b"raw-c2s"

    def test_empty_osu_token_header_still_selects_polling_branch(self) -> None:
        """空文字列の osu-token も login ではなく polling branch を選ぶことを検証する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.
        """
        client, login_workflow, polling_workflow = _make_client()

        response = client.post("/", content=b"raw-c2s", headers={"osu-token": ""})

        assert response.content == b"polling-bytes"
        assert _calls(login_workflow, polling_workflow) == _WorkflowCalls(
            login_count=0,
            polling_count=1,
        )
        assert polling_workflow.inputs[0].token == ""
