"""Tests for BanchoEndpoint HTTP boundary behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from osu_server.transports.bancho.endpoint import BanchoEndpoint
from osu_server.transports.bancho.workflows import (
    LoginWorkflowInput,
    LoginWorkflowResult,
    PollingWorkflowInput,
    PollingWorkflowResult,
)


@dataclass(slots=True, frozen=True)
class _WorkflowCalls:
    login_count: int
    polling_count: int


@final
class _RecordingLoginWorkflow:
    """Login workflow fake that records endpoint input mapping."""

    _result: LoginWorkflowResult
    inputs: list[LoginWorkflowInput]

    def __init__(self, result: LoginWorkflowResult) -> None:
        self._result = result
        self.inputs = []

    async def execute(self, workflow_input: LoginWorkflowInput) -> LoginWorkflowResult:
        self.inputs.append(workflow_input)
        return self._result


@final
class _RecordingPollingWorkflow:
    """Polling workflow fake that records endpoint input mapping."""

    _result: PollingWorkflowResult
    inputs: list[PollingWorkflowInput]

    def __init__(self, result: PollingWorkflowResult) -> None:
        self._result = result
        self.inputs = []

    async def execute(self, workflow_input: PollingWorkflowInput) -> PollingWorkflowResult:
        self.inputs.append(workflow_input)
        return self._result


def _make_client(
    *,
    login_result: LoginWorkflowResult | None = None,
    polling_result: PollingWorkflowResult | None = None,
) -> tuple[TestClient, _RecordingLoginWorkflow, _RecordingPollingWorkflow]:
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
    return _WorkflowCalls(
        login_count=len(login_workflow.inputs),
        polling_count=len(polling_workflow.inputs),
    )


class TestBanchoEndpoint:
    def test_without_osu_token_header_delegates_to_login_workflow(self) -> None:
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
        client, login_workflow, polling_workflow = _make_client()

        response = client.post("/", content=b"raw-c2s", headers={"osu-token": ""})

        assert response.content == b"polling-bytes"
        assert _calls(login_workflow, polling_workflow) == _WorkflowCalls(
            login_count=0,
            polling_count=1,
        )
        assert polling_workflow.inputs[0].token == ""
