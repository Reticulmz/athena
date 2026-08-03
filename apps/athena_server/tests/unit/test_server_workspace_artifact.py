"""Athena server wheelのinstalled entrypoint contractを検証するmodule."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SERVER_WORKSPACE_ROOT = REPOSITORY_ROOT / "apps" / "athena_server"
ARTIFACT_VERIFIER_PATH = SERVER_WORKSPACE_ROOT / "scripts" / "verify_artifact.py"


@pytest.mark.timeout(300)
def test_server_workspace_verifies_wheel_only_entrypoints() -> None:
    """Server ownerのverifierがclean wheelだけからpublic entrypointを検証することを確認する.

    Temporary directoryのconsumerへwheelをinstallし、source checkoutやeditable Athena packageへ
    fallbackせず`osu_server`、`athena_cli`、app、worker broker、`athena` commandをsmoke testする.

    Returns:
        None: owner-owned artifact verifierの成功と全smoke outcomeを確認して完了する.
    """
    result = subprocess.run(
        [sys.executable, str(ARTIFACT_VERIFIER_PATH)],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stderr
    assert "server wheel archive verified" in result.stdout
    assert "locked isolated consumer dependencies verified" in result.stdout
    assert "installed dependency closure verified" in result.stdout
    assert "installed namespaces verified" in result.stdout
    assert "installed Alembic config resolution verified" in result.stdout
    assert "isolated direct app import verified" in result.stdout
    assert "installed app entrypoint verified" in result.stdout
    assert "installed worker broker verified" in result.stdout
    assert "installed athena console entrypoint verified" in result.stdout
    assert "athena server wheel artifact verification passed" in result.stdout
