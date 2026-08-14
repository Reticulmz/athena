"""Crypto workspaceのinstalled artifact検証入口を検証するmodule."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CRYPTO_WORKSPACE_ROOT = REPOSITORY_ROOT / "packages" / "athena_crypto"
ARTIFACT_VERIFIER_PATH = CRYPTO_WORKSPACE_ROOT / "scripts" / "verify_artifact.py"
PUBLIC_TYPING_ROOT = CRYPTO_WORKSPACE_ROOT / "typings" / "athena_crypto"
CI_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"


def test_crypto_workspace_owns_public_typing_source() -> None:
    """Crypto packageがdesign指定のowner pathでpublic typing sourceを持つことを検証する.

    Root private stubやpackage rootの単独`.pyi`ではなく、package owner配下のPython source treeが
    wheelに同梱するstubと`py.typed` markerの唯一のsourceになることを確認する.

    Returns:
        None: public typing sourceの配置とMaturinのsource root設定を検証して完了する.
    """
    manifest_source = (CRYPTO_WORKSPACE_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert (PUBLIC_TYPING_ROOT / "__init__.pyi").is_file()
    assert (PUBLIC_TYPING_ROOT / "athena_crypto.pyi").is_file()
    assert (PUBLIC_TYPING_ROOT / "py.typed").is_file()
    assert not (CRYPTO_WORKSPACE_ROOT / "athena_crypto.pyi").exists()
    assert 'python-source = "typings"' in manifest_source


def test_installed_native_test_verifier_rejects_zero_discovery(tmp_path: Path) -> None:
    """Artifact verifierがnative testを一件も発見できない場合に明示的に失敗することを検証する.

    空のtest directoryを渡したconsumer processでinternal verifierを実行し、unittestの成功終了を
    crypto behavior testの成功として誤認しないことを確認する.

    Args:
        tmp_path (Path): testを含まないconsumer working directoryを作るfixture.

    Returns:
        None: zero-test discoveryが明示的なRuntimeErrorになることを検証して完了する.
    """
    probe_source = """
import importlib.util
import os
import sys
from pathlib import Path

verifier_path = Path(sys.argv[1])
empty_test_directory = Path(sys.argv[2])
specification = importlib.util.spec_from_file_location("artifact_verifier", verifier_path)
assert specification is not None
assert specification.loader is not None
verifier = importlib.util.module_from_spec(specification)
specification.loader.exec_module(verifier)

try:
    verifier._verify_installed_native_tests(
        Path(sys.executable),
        Path.cwd(),
        os.environ,
        tests_directory=empty_test_directory,
    )
except RuntimeError as error:
    if "No package-owned native tests were discovered" in str(error):
        raise SystemExit(0)
    raise

raise SystemExit("Verifier accepted zero discovered native tests")
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            probe_source,
            str(ARTIFACT_VERIFIER_PATH),
            str(tmp_path),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_ci_rebuilds_editable_crypto_extension_after_each_venv_restore() -> None:
    """CI consumer jobがcache外のeditable native extensionを各checkoutで再構築することを検証する.

    Setup jobの`.venv` cacheにはsource treeへ生成されるnative extensionが含まれないため、native
    validationを実行する各consumer jobはcache restore後にcurrent sourceからathena-cryptoだけを
    明示的に再installする.

    Returns:
        None: 3つのconsumer jobでrestore後にreinstallする順序を検証して完了する.
    """
    workflow_source = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    restore_step = "uses: actions/cache/restore@v4"
    reinstall_command = "run: uv sync --locked --reinstall-package athena-crypto"

    assert workflow_source.count(restore_step) == 3
    assert workflow_source.count(reinstall_command) == 3
    restore_offsets = [
        offset
        for offset in range(len(workflow_source))
        if workflow_source.startswith(restore_step, offset)
    ]
    reinstall_offsets = [
        offset
        for offset in range(len(workflow_source))
        if workflow_source.startswith(reinstall_command, offset)
    ]
    assert all(
        restore_offset < reinstall_offset
        for restore_offset, reinstall_offset in zip(
            restore_offsets, reinstall_offsets, strict=True
        )
    )


@pytest.mark.timeout(300)
def test_root_suite_runs_crypto_artifact_verifier_once() -> None:
    """Root test suiteがcrypto ownerのwheel-only verifierを一度実行することを検証する.

    verifierは一時directoryでwheelを作成し、source treeとroot conftestをconsumerから隔離して
    native importとpublic typing artifactを確認する。そのためroot testはcrypto implementationを
    直接importせず、この唯一のowner入口の成功だけを確認する.

    Returns:
        None: crypto artifact verifierの成功と検証済みoutcomeを確認して完了する.
    """
    result = subprocess.run(
        [sys.executable, str(ARTIFACT_VERIFIER_PATH)],
        cwd=CRYPTO_WORKSPACE_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stderr
    assert "athena_crypto wheel artifact verification passed" in result.stdout
