"""Moved path consumerの監査契約を検証するmodule."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AUDIT_TOOL_PATH = REPOSITORY_ROOT / "tools" / "monorepo_migration" / "verify_path_consumers.py"
AUDIT_POLICY_PATH = REPOSITORY_ROOT / "tools" / "monorepo_migration" / "path_consumer_audit.json"


def _run_audit(
    *arguments: str,
    repository_root: Path = REPOSITORY_ROOT,
) -> subprocess.CompletedProcess[str]:
    """Path consumer監査CLIを指定repositoryへ実行する.

    Args:
        *arguments (str): 監査CLIへ渡す追加argument.
        repository_root (Path): 監査対象repositoryのroot path.

    Returns:
        subprocess.CompletedProcess[str]: 監査結果とexit statusを含むprocess result.
    """
    return subprocess.run(
        [
            sys.executable,
            str(AUDIT_TOOL_PATH),
            "--repository-root",
            str(repository_root),
            "--policy",
            str(AUDIT_POLICY_PATH),
            *arguments,
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _write_fixture_policy(tmp_path: Path) -> tuple[Path, Path]:
    """監査fixtureと最小policyを作成する.

    Args:
        tmp_path (Path): fixtureを作成するpytest temporary directory.

    Returns:
        tuple[Path, Path]: fixture repository rootとpolicy path.
    """
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _ = (repository_root / "current.md").write_text("", encoding="utf-8")
    _ = (repository_root / "history.md").write_text("", encoding="utf-8")
    policy_path = tmp_path / "policy.json"
    _ = policy_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scan_paths": ["current.md", "history.md"],
                "excluded_paths": [
                    {
                        "glob": "history.md",
                        "reason": "historical evidence is non-normative",
                    }
                ],
                "rules": [
                    {
                        "id": "root_tests",
                        "regex": r"(?<![A-Za-z0-9_./-])tests/",
                        "replacement": "apps/athena_server/tests/",
                    }
                ],
                "allow": [],
            }
        ),
        encoding="utf-8",
    )
    return repository_root, policy_path


def test_current_repository_audit_passes_after_cleanup() -> None:
    """Current repository auditがcleanup後に成功することを検証する.

    Returns:
        None: stale consumer、unexpected artifact、削除予定artifactが残っていないことを確認する.
    """
    result = _run_audit()

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "path consumer audit passed"


def test_audit_reports_stale_consumer_with_replacement_and_line_number(tmp_path: Path) -> None:
    """現在consumerの旧path参照をline numberと移行先付きで報告することを検証する.

    Args:
        tmp_path (Path): stale referenceを含むfixture repositoryのtemporary directory.

    Returns:
        None: 監査がnon-zeroとなり、findingの主要情報をstderrへ出力することを確認して完了する.
    """
    repository_root, policy_path = _write_fixture_policy(tmp_path)
    _ = (repository_root / "current.md").write_text(
        "current fixture: tests/fixtures/old.json\n",
        encoding="utf-8",
    )

    result = _run_audit("--policy", str(policy_path), repository_root=repository_root)

    assert result.returncode == 1
    assert "current.md:1" in result.stderr
    assert "tests/" in result.stderr
    assert "apps/athena_server/tests/" in result.stderr


def test_audit_excludes_declared_historical_paths(tmp_path: Path) -> None:
    """policyで宣言したhistorical pathをstale consumerとして扱わないことを検証する.

    Args:
        tmp_path (Path): historical referenceを含むfixture repositoryのtemporary directory.

    Returns:
        None: 除外されたpathの参照があっても監査が成功することを確認して完了する.
    """
    repository_root, policy_path = _write_fixture_policy(tmp_path)
    _ = (repository_root / "history.md").write_text(
        "historical fixture: tests/fixtures/old.json\n",
        encoding="utf-8",
    )

    result = _run_audit("--policy", str(policy_path), repository_root=repository_root)

    assert result.returncode == 0, result.stderr


def test_audit_distinguishes_forbidden_artifacts_from_expected_cleanup(
    tmp_path: Path,
) -> None:
    """Forbidden artifactとexpected cleanup artifactを別のfindingとして報告する.

    Args:
        tmp_path (Path): fixture repositoryとpolicyを置くtemporary directory.

    Returns:
        None: scope外artifactと削除予定artifactの両方が区別されることを検証して完了する.
    """
    repository_root, policy_path = _write_fixture_policy(tmp_path)
    forbidden_path = repository_root / "apps" / "athena_web"
    forbidden_path.mkdir(parents=True)
    _ = (repository_root / "legacy.sh").write_text("", encoding="utf-8")
    policy = cast("dict[str, object]", json.loads(policy_path.read_text(encoding="utf-8")))
    policy["expected_cleanup_artifacts"] = [
        {"path": "legacy.sh", "reason": "legacy helper is removed in cleanup"}
    ]
    policy["forbidden_artifacts"] = [
        {"path": "apps/athena_web", "reason": "frontend workspace is out of scope"}
    ]
    _ = policy_path.write_text(json.dumps(policy), encoding="utf-8")

    result = _run_audit("--policy", str(policy_path), repository_root=repository_root)

    assert result.returncode == 1
    assert "forbidden monorepo artifact: apps/athena_web" in result.stderr
    assert "expected cleanup artifact remains: legacy.sh" in result.stderr


def test_repository_policy_declares_historical_kiro_and_transitional_exceptions() -> None:
    """Repository policyがhistorical Kiro snapshotとtransitional artifactの理由を検証する.

    Returns:
        None: 必須exception globと説明を確認して完了する.
    """
    policy = cast(
        "dict[str, object]",
        json.loads(AUDIT_POLICY_PATH.read_text(encoding="utf-8")),
    )
    scan_paths = set(cast("list[str]", policy["scan_paths"]))
    raw_exclusions = cast("list[object]", policy["excluded_paths"])
    exclusions = {
        cast("dict[str, str]", entry)["glob"]: cast("dict[str, str]", entry)["reason"]
        for entry in raw_exclusions
    }
    expected_cleanup_paths = {
        cast("dict[str, str]", entry)["path"]
        for entry in cast("list[object]", policy["expected_cleanup_artifacts"])
    }
    forbidden_artifact_paths = {
        cast("dict[str, str]", entry)["path"]
        for entry in cast("list[object]", policy["forbidden_artifacts"])
    }

    assert ".kiro/specs/**" in exclusions
    assert "historical" in exclusions[".kiro/specs/**"].lower()
    assert ".kiro/specs/monorepo-migration/**" in exclusions
    assert "approved" in exclusions[".kiro/specs/monorepo-migration/**"].lower()
    assert "docs/agent-python.md" in scan_paths
    assert "apps/athena_server/docs" in scan_paths
    assert "apps/athena_server/src/athena_cli/stable_verification" in scan_paths
    assert "apps/athena_server/tests/unit/athena_cli/stable_verification" in scan_paths
    assert "tools/monorepo_migration/verify_preflight_baseline.py" in exclusions
    assert (
        "transitional"
        in exclusions["tools/monorepo_migration/verify_preflight_baseline.py"].lower()
    )
    assert {"scripts/ci.sh", "scripts/dev-tasks.sh"} <= expected_cleanup_paths
    assert ".venv" not in expected_cleanup_paths
    assert {
        "apps/athena_web",
        "tests/system",
        "apps/athena_server/uv.lock",
        "packages/athena_crypto/uv.lock",
        "packages/athena_pp",
        "package.json",
    } <= forbidden_artifact_paths
