"""Python workspaceのroot validation contractを検証するmodule."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import cast

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ROOT_MANIFEST_PATH = REPOSITORY_ROOT / "pyproject.toml"
ROOT_CI_SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "ci.sh"
FLAKE_PATH = REPOSITORY_ROOT / "flake.nix"
WORKSPACE_VALIDATION_TOOL_PATH = (
    REPOSITORY_ROOT / "tools" / "monorepo_migration" / "verify_workspace_validation.py"
)
SERVER_WORKSPACE_PATH = "apps/athena_server"
CRYPTO_WORKSPACE_PATH = "packages/athena_crypto"
ROOT_GITLINT_TEST_PATH = "tests/unit/test_forbidden_words.py"
SERVER_WORKSPACE_TASKS_PATH = (
    REPOSITORY_ROOT / SERVER_WORKSPACE_PATH / "scripts" / "workspace_tasks.py"
)
EXPECTED_WORKSPACE_MEMBERS = [SERVER_WORKSPACE_PATH, CRYPTO_WORKSPACE_PATH]
REQUIRED_TYPE_CHECK_PATHS = (
    "apps/athena_server/src",
    "apps/athena_server/scripts",
    "tests",
    "apps/athena_server/tests",
    "packages/athena_crypto/typings",
    "packages/athena_crypto/scripts",
    "packages/athena_crypto/tests",
    "tools",
    "gitlint_rules",
)
TYPE_CHECKER_COMMAND = "tools/monorepo_migration/verify_workspace_validation.py --run-basedpyright"
type TomlTable = dict[str, object]


def _toml_table(value: object) -> TomlTable:
    """TOML valueをtableとして検証して返す.

    Args:
        value (object): TOML parserから取得した未検証の値.

    Returns:
        TomlTable: tableとして扱えるmapping.

    Raises:
        AssertionError: valueがTOML tableではない場合.
    """
    assert isinstance(value, dict)
    return cast("TomlTable", value)


def _workspace_members() -> list[str]:
    """Root manifestから初期Python workspace memberを取得する.

    Returns:
        list[str]: root uv workspaceが宣言するmember pathの順序付きlist.

    Raises:
        AssertionError: manifestがworkspace memberを文字列listとして定義しない場合.
    """
    manifest = _toml_table(tomllib.loads(ROOT_MANIFEST_PATH.read_text(encoding="utf-8")))
    tool = _toml_table(manifest["tool"])
    uv = _toml_table(tool["uv"])
    workspace = _toml_table(uv["workspace"])
    raw_members = workspace["members"]

    assert isinstance(raw_members, list)
    members = cast("list[object]", raw_members)
    assert all(isinstance(member, str) for member in members)
    return cast("list[str]", members)


def _shell_function_body(script: str, function_name: str) -> str:
    """Bash sourceから指定functionのbodyを取り出す.

    Args:
        script (str): function definitionを含むBash source全体.
        function_name (str): bodyを取り出すfunction名.

    Returns:
        str: opening/closing braceを除いたfunction body.

    Raises:
        AssertionError: 指定functionがsourceに存在しない場合.
    """
    marker = f"{function_name}() {{\n"
    start = script.find(marker)
    assert start >= 0
    body_start = start + len(marker)
    body_end = script.find("\n}\n", body_start)
    assert body_end >= 0
    return script[body_start:body_end]


def _write_workspace_fixture(tmp_path: Path, *, include_artifact_tests: bool) -> Path:
    """Workspace validation CLIを隔離検証する最小repositoryを作成する.

    Args:
        tmp_path (Path): fixture repositoryを作るpytest temporary directory.
        include_artifact_tests (bool): server/crypto artifact contract testを配置するか.

    Returns:
        Path: root `pyproject.toml`を含むfixture repository directory.
    """
    repository_root = tmp_path / "repository"
    server_root = repository_root / SERVER_WORKSPACE_PATH
    crypto_root = repository_root / CRYPTO_WORKSPACE_PATH
    root_tests = repository_root / "tests"
    server_tests = server_root / "tests"
    crypto_tests = crypto_root / "tests"
    for directory in (root_tests, server_tests, crypto_tests):
        directory.mkdir(parents=True)
    _ = (repository_root / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["apps/athena_server", "packages/athena_crypto"]\n',
        encoding="utf-8",
    )
    for manifest_path in (server_root / "pyproject.toml", crypto_root / "pyproject.toml"):
        _ = manifest_path.write_text('[project]\nname = "fixture"\n', encoding="utf-8")
    _ = (repository_root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    root_gitlint_test = repository_root / ROOT_GITLINT_TEST_PATH
    root_gitlint_test.parent.mkdir(parents=True)
    _ = root_gitlint_test.write_text("", encoding="utf-8")
    _ = (server_tests / "test_server_behavior.py").write_text("", encoding="utf-8")
    _ = (crypto_tests / "test_crypto_behavior.py").write_text("", encoding="utf-8")
    if include_artifact_tests:
        _ = (server_tests / "test_server_workspace_artifact.py").write_text("", encoding="utf-8")
        _ = (server_tests / "test_crypto_workspace_artifact.py").write_text("", encoding="utf-8")
    return repository_root


def _run_workspace_validation(
    *arguments: str,
    repository_root: Path,
) -> subprocess.CompletedProcess[str]:
    """Workspace validation CLIを指定fixture repositoryに対して実行する.

    Args:
        *arguments (str): verifierへ渡す追加のCLI argument.
        repository_root (Path): `--repository-root`へ渡すfixture root.

    Returns:
        subprocess.CompletedProcess[str]: captured outputとexit statusを含むCLI実行結果.
    """
    return subprocess.run(
        [
            sys.executable,
            str(WORKSPACE_VALIDATION_TOOL_PATH),
            "--repository-root",
            str(repository_root),
            *arguments,
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=60,
    )


def test_root_quality_type_checks_initial_workspace_and_repository_tooling() -> None:
    """Root quality policyが初期workspaceとrepository toolingを型検査することを検証する.

    新しいworkspace memberまたはrepository-owned Python toolを追加した際に、Ruffだけが検査し
    Basedpyrightが静かに除外する状態を許可しない.

    Returns:
        None: workspace memberとroot/pre-commit type check inventoryを検証して完了する.
    """
    script = ROOT_CI_SCRIPT_PATH.read_text(encoding="utf-8")
    flake = FLAKE_PATH.read_text(encoding="utf-8")
    quality_body = _shell_function_body(script, "run_quality")

    assert _workspace_members() == EXPECTED_WORKSPACE_MEMBERS
    assert "tools/monorepo_migration/verify_workspace_validation.py" in quality_body
    assert "--run-basedpyright" in quality_body
    assert TYPE_CHECKER_COMMAND in flake
    manifest = _toml_table(tomllib.loads(ROOT_MANIFEST_PATH.read_text(encoding="utf-8")))
    tool = _toml_table(manifest["tool"])
    basedpyright_configuration = _toml_table(tool["basedpyright"])
    assert basedpyright_configuration["stubPath"] == "apps/athena_server/typings"
    assert basedpyright_configuration["extraPaths"] == [
        "apps/athena_server/src",
        "apps/athena_server",
    ]

    result = _run_workspace_validation("--type-check-paths", repository_root=REPOSITORY_ROOT)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == list(REQUIRED_TYPE_CHECK_PATHS)


def test_root_test_gate_covers_current_member_test_contracts() -> None:
    """Root test gateと設定が移設済みtestと一時Gitlint testを通すことを検証する.

    Server artifact testはapp/worker/CLI wheel entrypointを、crypto artifact testはisolated native
    consumer testとpublic typing artifactを検証する。root gateはworkspace verifierからcurrent
    memberのpytest rootを取得するため、Task 2.1のtest physical move後も対象漏れを起こさない.

    Returns:
        None: root pytest target、static設定、動的member test pathのcoverageを検証して完了する.
    """
    script = ROOT_CI_SCRIPT_PATH.read_text(encoding="utf-8")
    test_body = _shell_function_body(script, "run_test")

    verifier_command = "tools/monorepo_migration/verify_workspace_validation.py --pytest-paths"

    assert verifier_command in test_body
    result = _run_workspace_validation("--pytest-paths", repository_root=REPOSITORY_ROOT)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "tests",
        "apps/athena_server/tests",
        "tools/monorepo_migration/tests",
    ]
    manifest = _toml_table(tomllib.loads(ROOT_MANIFEST_PATH.read_text(encoding="utf-8")))
    tool = _toml_table(manifest["tool"])
    pytest_configuration = _toml_table(tool["pytest"])
    pytest_options = _toml_table(pytest_configuration["ini_options"])
    ruff_configuration = _toml_table(tool["ruff"])
    raw_test_paths = pytest_options["testpaths"]
    raw_source_paths = ruff_configuration["src"]
    ruff_lint_configuration = _toml_table(ruff_configuration["lint"])
    per_file_ignores = _toml_table(ruff_lint_configuration["per-file-ignores"])

    assert raw_test_paths == [
        "tests",
        "apps/athena_server/tests",
        "tools/monorepo_migration/tests",
    ]
    assert raw_source_paths == [
        "apps/athena_server/src",
        "apps/athena_server/tests",
        "tests",
        "packages/athena_crypto/typings",
    ]
    assert "tests/**/*.py" in per_file_ignores


def test_workspace_verifier_rejects_member_tests_without_artifact_contracts(
    tmp_path: Path,
) -> None:
    """Workspace verifierがartifact contractを持たないmember test rootを拒否することを検証する.

    Package native testを通常のpytest discoveryだけで成功と誤認せず、server/crypto wheel behaviorを
    検証するcontract testがpytest rootに存在するまでroot gateを停止させる.

    Args:
        tmp_path (Path): 最小workspace fixtureを隔離するpytest temporary directory.

    Returns:
        None: artifact contract未配置のworkspaceがnon-zeroになることを検証して完了する.
    """
    repository_root = _write_workspace_fixture(tmp_path, include_artifact_tests=False)

    result = _run_workspace_validation("--pytest-paths", repository_root=repository_root)

    assert result.returncode != 0
    assert "test_server_workspace_artifact.py" in result.stderr
    assert "test_crypto_workspace_artifact.py" in result.stderr


def test_workspace_verifier_rejects_member_lockfiles(tmp_path: Path) -> None:
    """Workspace verifierがmember lockfileをsingle-lock違反として拒否することを検証する.

    Root lockとcrypto workspace内の`uv.lock`が共存するfixtureを検証し、workspace固有の
    dependency resolutionがroot gateを通過しないことを確認する.

    Args:
        tmp_path (Path): member lockfileを置く隔離workspace fixtureのroot directory.

    Returns:
        None: member lockfileを含むworkspaceがnon-zeroになることを検証して完了する.
    """
    repository_root = _write_workspace_fixture(tmp_path, include_artifact_tests=True)
    member_lockfile = repository_root / CRYPTO_WORKSPACE_PATH / "uv.lock"
    _ = member_lockfile.write_text("version = 1\n", encoding="utf-8")

    result = _run_workspace_validation("--pytest-paths", repository_root=repository_root)

    assert result.returncode != 0
    assert member_lockfile.relative_to(repository_root).as_posix() in result.stderr


def test_workspace_verifier_rejects_nested_lockfiles(tmp_path: Path) -> None:
    """Workspace verifierがmember外に追加されたlockfileもsingle-lock違反として拒否する.

    Tooling directoryなどに追加された`uv.lock`がroot workflowのdependency resolutionを分岐させ、
    member直下だけの検査を回避する状態を許可しない.

    Args:
        tmp_path (Path): nested lockfileを置く隔離workspace fixtureのroot directory.

    Returns:
        None: root外のnested lockfileを含むworkspaceがnon-zeroになることを検証して完了する.
    """
    repository_root = _write_workspace_fixture(tmp_path, include_artifact_tests=True)
    nested_lockfile = repository_root / "tools" / "monorepo_migration" / "uv.lock"
    nested_lockfile.parent.mkdir(parents=True)
    _ = nested_lockfile.write_text("version = 1\n", encoding="utf-8")

    result = _run_workspace_validation("--pytest-paths", repository_root=repository_root)

    assert result.returncode != 0
    assert nested_lockfile.relative_to(repository_root).as_posix() in result.stderr


def test_workspace_verifier_requires_the_authoritative_root_lockfile(tmp_path: Path) -> None:
    """Workspace verifierがroot `uv.lock`の欠落をsingle-lock違反として拒否する.

    Member lockfileが存在しなくてもauthoritative lock自体がなければlocked validationを再現できない
    ため、root lockだけが唯一存在することを検証する.

    Args:
        tmp_path (Path): root lockfileを除く隔離workspace fixtureのroot directory.

    Returns:
        None: root lockfileを欠くworkspaceがnon-zeroになることを検証して完了する.
    """
    repository_root = _write_workspace_fixture(tmp_path, include_artifact_tests=True)
    root_lockfile = repository_root / "uv.lock"
    root_lockfile.unlink()

    result = _run_workspace_validation("--pytest-paths", repository_root=repository_root)

    assert result.returncode != 0
    assert "exactly the root uv.lock" in result.stderr


def test_workspace_verifier_rejects_an_unexpected_workspace_member(tmp_path: Path) -> None:
    """Workspace verifierが初期contract外のmember追加を拒否することを検証する.

    新しいworkspaceをroot validationへ無宣言で追加した場合、test/quality coverageが曖昧なまま
    通過しないよう、manifestのmember list自体を機械検証する.

    Args:
        tmp_path (Path): 最小workspace fixtureを隔離するpytest temporary directory.

    Returns:
        None: 初期contractと異なるmember listがnon-zeroになることを検証して完了する.
    """
    repository_root = _write_workspace_fixture(tmp_path, include_artifact_tests=True)
    root_manifest_path = repository_root / "pyproject.toml"
    _ = root_manifest_path.write_text(
        """[tool.uv.workspace]
members = [
    "apps/athena_server",
    "packages/athena_crypto",
    "apps/athena_admin",
]
""",
        encoding="utf-8",
    )

    result = _run_workspace_validation("--pytest-paths", repository_root=repository_root)

    assert result.returncode != 0
    assert "Initial workspace members changed" in result.stderr


def test_workspace_verifier_permits_only_transitional_root_gitlint_test(
    tmp_path: Path,
) -> None:
    """Workspace verifierが一時的なroot Gitlint testだけを許可することを検証する.

    Task 3.4でGitlint toolingを移設するまで、`tests/unit/test_forbidden_words.py`だけはrootに
    残る。一方、server testまたは別のtooling testがrootに残るとowner boundaryが曖昧になるため、
    verifierはnon-zeroで停止させる.

    Args:
        tmp_path (Path): test physical move後を模したworkspace fixtureを隔離するdirectory.

    Returns:
        None: 許可されたGitlint testのdiscoveryと、他root testの拒否を検証して完了する.
    """
    repository_root = _write_workspace_fixture(tmp_path, include_artifact_tests=True)
    root_tests = repository_root / "tests"
    allowed_root_test = repository_root / ROOT_GITLINT_TEST_PATH
    pytest_result = _run_workspace_validation("--pytest-paths", repository_root=repository_root)
    type_check_result = _run_workspace_validation(
        "--type-check-paths",
        repository_root=repository_root,
    )

    assert allowed_root_test.is_file()
    assert pytest_result.returncode == 0, pytest_result.stderr
    assert type_check_result.returncode == 0, type_check_result.stderr
    assert pytest_result.stdout.splitlines() == ["tests", "apps/athena_server/tests"]
    assert type_check_result.stdout.splitlines() == list(REQUIRED_TYPE_CHECK_PATHS)

    root_direct_test_path = root_tests / "test_forbidden_words.py"
    _ = root_direct_test_path.write_text("", encoding="utf-8")

    root_direct_result = _run_workspace_validation(
        "--pytest-paths",
        repository_root=repository_root,
    )

    assert root_direct_result.returncode != 0
    assert (
        root_direct_test_path.relative_to(repository_root).as_posix() in root_direct_result.stderr
    )

    root_direct_test_path.unlink()
    root_unit_test_path = root_tests / "unit" / "test_repository_tooling.py"
    _ = root_unit_test_path.write_text("", encoding="utf-8")

    root_unit_result = _run_workspace_validation(
        "--pytest-paths",
        repository_root=repository_root,
    )

    assert root_unit_result.returncode != 0
    assert root_unit_test_path.relative_to(repository_root).as_posix() in root_unit_result.stderr


def test_workspace_verifier_discovers_canonical_repository_tooling_test_roots(
    tmp_path: Path,
) -> None:
    """Workspace verifierがtoolsとgitlint ownerのcanonical test rootをpytestへ含める.

    Repository toolingのtestをroot `tests/`だけへ置くことに暗黙依存せず、owner配下の`tests`
    directoryをroot test gateが直接実行することを確認する.

    Args:
        tmp_path (Path): tooling-owned test rootを置く隔離workspace fixtureのroot directory.

    Returns:
        None: applicationとtoolingのcanonical test rootが順序付きpytest targetになることを検証して
            完了する.
    """
    repository_root = _write_workspace_fixture(tmp_path, include_artifact_tests=True)
    tool_tests = repository_root / "tools" / "monorepo_migration" / "tests"
    gitlint_tests = repository_root / "gitlint_rules" / "tests"
    for test_directory in (tool_tests, gitlint_tests):
        test_directory.mkdir(parents=True)
    _ = (tool_tests / "test_tooling_behavior.py").write_text("", encoding="utf-8")
    _ = (gitlint_tests / "test_rule_behavior.py").write_text("", encoding="utf-8")

    result = _run_workspace_validation("--pytest-paths", repository_root=repository_root)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "tests",
        "apps/athena_server/tests",
        "tools/monorepo_migration/tests",
        "gitlint_rules/tests",
    ]


def test_workspace_verifier_rejects_tooling_tests_outside_a_canonical_test_root(
    tmp_path: Path,
) -> None:
    """Workspace verifierがtooling owner配下の非canonical test fileを拒否する.

    `tools`または`gitlint_rules`直下へtest fileを置いてroot gateが見落とす状態を防ぐため、
    tooling testはowner配下の`tests` directoryへ明示的に配置させる.

    Args:
        tmp_path (Path): 非canonical tooling test fileを置く隔離workspace fixtureのroot directory.

    Returns:
        None: canonical test root外のtooling testがnon-zeroになることを検証して完了する.
    """
    repository_root = _write_workspace_fixture(tmp_path, include_artifact_tests=True)
    orphaned_test = repository_root / "tools" / "monorepo_migration" / "test_orphaned.py"
    orphaned_test.parent.mkdir(parents=True)
    _ = orphaned_test.write_text("", encoding="utf-8")

    result = _run_workspace_validation("--pytest-paths", repository_root=repository_root)

    assert result.returncode != 0
    assert orphaned_test.relative_to(repository_root).as_posix() in result.stderr


@pytest.mark.timeout(600)
def test_server_workspace_operations_complete_without_a_frontend_member(
    tmp_path: Path,
) -> None:
    """Server workspaceのlocked sync、build、quality、testがfrontendなしで完了することを検証する.

    Root workspaceからserver-owned task entrypointを順に実行し、temporary virtual environmentと
    wheel outputだけを使う。各operationは存在しないfrontend workspaceへfallbackできないため、
    frontend memberへの依存が追加されるとそのoperationのnon-zero exitで契約が失敗する.

    Args:
        tmp_path (Path): sync用virtual environmentとbuild outputを隔離するtemporary directory.

    Returns:
        None: server workspaceの全operationがfrontendなしで成功することを検証して完了する.
    """
    assert "apps/athena_web" not in _workspace_members()
    assert not (REPOSITORY_ROOT / "apps" / "athena_web").exists()

    environment = os.environ.copy()
    environment["UV_PROJECT_ENVIRONMENT"] = str(tmp_path / "server-venv")
    operations = (
        ("sync",),
        ("build", "--output-directory", str(tmp_path / "wheels")),
        ("quality",),
        ("test",),
    )
    for operation in operations:
        result = subprocess.run(
            [sys.executable, str(SERVER_WORKSPACE_TASKS_PATH), *operation],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=600,
        )

        assert result.returncode == 0, (
            f"Server workspace operation failed: {operation!r}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
