"""Tests for bancho workflow contract value objects."""

import ast
import inspect
from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest

from osu_server.transports.stable.bancho import workflows
from osu_server.transports.stable.bancho.workflows import (
    LoginWorkflowInput,
    LoginWorkflowResult,
    PollingWorkflowInput,
    PollingWorkflowResult,
)
from osu_server.transports.stable.bancho.workflows import login as login_workflow_module
from osu_server.transports.stable.bancho.workflows import polling as polling_workflow_module


def _try_set_attribute(instance: object, name: str, value: object) -> None:
    setattr(instance, name, value)


def test_login_workflow_contracts_are_transport_local_value_objects() -> None:
    login_input = LoginWorkflowInput(body=b"login", headers={"X-Real-IP": "127.0.0.1"})
    login_result = LoginWorkflowResult(content=b"s2c", cho_token="token")

    assert is_dataclass(LoginWorkflowInput)
    assert is_dataclass(LoginWorkflowResult)
    assert [field.name for field in fields(LoginWorkflowInput)] == ["body", "headers"]
    assert [field.name for field in fields(LoginWorkflowResult)] == ["content", "cho_token"]
    assert login_input.body == b"login"
    assert login_result.content == b"s2c"
    assert login_result.cho_token == "token"
    assert not hasattr(login_input, "__dict__")
    assert not hasattr(login_result, "__dict__")

    with pytest.raises(FrozenInstanceError):
        _try_set_attribute(login_result, "cho_token", None)


def test_polling_workflow_contracts_are_transport_local_value_objects() -> None:
    polling_input = PollingWorkflowInput(token="token", body=b"c2s")
    polling_result = PollingWorkflowResult(content=b"queued-s2c")

    assert is_dataclass(PollingWorkflowInput)
    assert is_dataclass(PollingWorkflowResult)
    assert [field.name for field in fields(PollingWorkflowInput)] == ["token", "body"]
    assert [field.name for field in fields(PollingWorkflowResult)] == ["content"]
    assert polling_input.token == "token"
    assert polling_input.body == b"c2s"
    assert polling_result.content == b"queued-s2c"
    assert not hasattr(polling_input, "__dict__")
    assert not hasattr(polling_result, "__dict__")

    with pytest.raises(FrozenInstanceError):
        _try_set_attribute(polling_result, "content", b"changed")


def test_workflow_contract_modules_do_not_import_starlette() -> None:
    workflow_sources = (
        inspect.getsource(login_workflow_module),
        inspect.getsource(polling_workflow_module),
    )
    imported_modules: list[str] = []
    for source in workflow_sources:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.append(node.module)

    assert all(not module.startswith("starlette") for module in imported_modules)


def test_workflow_package_does_not_export_legacy_login_handler_alias() -> None:
    assert "LoginHandler" not in workflows.__all__
    assert not hasattr(workflows, "LoginHandler")
