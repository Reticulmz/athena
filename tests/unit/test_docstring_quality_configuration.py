"""Docstring品質toolchainの設定契約を検証する."""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CI_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "ci.sh"
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
UV_LOCK_PATH = PROJECT_ROOT / "uv.lock"
FIRST_PARTY_PYTHON_ROOTS = (
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "alembic",
    PROJECT_ROOT / "gitlint_rules",
    PROJECT_ROOT / "athena-crypto/tests",
    PROJECT_ROOT / ".agents",
)
DOCSTRING_NOQA_PATTERN = re.compile(
    r"#\s*noqa(?::[^\n]*)?\b(?:D\d{3}|DOC\d{3})\b",
    flags=re.IGNORECASE,
)

type TomlTable = dict[str, object]


def _environment_without_git_local_context() -> dict[str, str]:
    """現在のenvironmentからGit worktree固有の変数を除去する.

    Returns:
        dict[str, str]: 任意のGit repositoryをcwdで選べるようGit local variableを除去した
            environment.

    Raises:
        AssertionError: Gitがlocal environment variable名を列挙できない場合.
    """
    environment = os.environ.copy()
    completed_process = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    stdout = completed_process.stdout

    assert stdout is not None
    assert completed_process.returncode == 0, completed_process.stderr

    for variable_name in stdout.splitlines():
        _ = environment.pop(variable_name, None)

    return environment


def _run_ci_command(
    *arguments: str,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    """指定したworktreeからLocal CI subcommandを実行する.

    Args:
        *arguments (str): `scripts/ci.sh`へ渡すsubcommandと追加引数.
        cwd (Path): commandを実行しGit worktreeを判定させるdirectory.

    Returns:
        subprocess.CompletedProcess[str]: 標準出力、標準エラー、exit statusを含む実行結果.
    """
    return subprocess.run(
        [str(CI_SCRIPT_PATH), *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=_environment_without_git_local_context(),
    )


def _git_indexed_python_files(repository_root: Path) -> list[str]:
    """Git indexにあるPython source pathをNUL区切りで取得する.

    Args:
        repository_root (Path): inventoryを取得するGit worktreeのroot directory.

    Returns:
        list[str]: index内の`.py` pathをGitの順序で並べたlist.

    Raises:
        AssertionError: Git inventory commandが正常終了しない場合.
    """
    completed_process = subprocess.run(
        ["git", "ls-files", "--cached", "-z", "--", "*.py"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        env=_environment_without_git_local_context(),
    )
    stdout = completed_process.stdout
    stderr = completed_process.stderr

    assert stdout is not None
    assert stderr is not None
    assert completed_process.returncode == 0, stderr.decode(encoding="utf-8")

    return [path.decode(encoding="utf-8") for path in stdout.split(b"\0") if path]


def _initialize_temporary_git_repository(repository_root: Path) -> None:
    """空の一時Git worktreeを初期化する.

    Args:
        repository_root (Path): 新しくGit repositoryとして初期化する存在しないdirectory.

    Returns:
        None: 一時repositoryを作成してindexを空のままにする.

    Raises:
        AssertionError: Git repositoryの初期化に失敗した場合.
    """
    repository_root.mkdir()
    completed_process = subprocess.run(
        ["git", "init", "--quiet"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        env=_environment_without_git_local_context(),
    )

    assert completed_process.returncode == 0, completed_process.stderr


def _git_worktree_context_environment(repository_root: Path) -> dict[str, str]:
    """Git hookがrepository contextとして継承する環境変数を取得する.

    Args:
        repository_root (Path): Git contextの値を取得する初期化済みworktreeのroot directory.

    Returns:
        dict[str, str]: `GIT_DIR`、`GIT_WORK_TREE`、`GIT_INDEX_FILE`を含むenvironment mapping.

    Raises:
        AssertionError: Gitがworktree metadataを解決できない場合.
    """
    git_directory_process = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        env=_environment_without_git_local_context(),
    )
    git_index_process = subprocess.run(
        ["git", "rev-parse", "--git-path", "index"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        env=_environment_without_git_local_context(),
    )
    git_directory = git_directory_process.stdout
    git_index_path = git_index_process.stdout

    assert git_directory is not None
    assert git_index_path is not None
    assert git_directory_process.returncode == 0, git_directory_process.stderr
    assert git_index_process.returncode == 0, git_index_process.stderr

    return {
        "GIT_DIR": git_directory.strip(),
        "GIT_WORK_TREE": str(repository_root),
        "GIT_INDEX_FILE": git_index_path.strip(),
    }


def _load_toml(path: Path) -> TomlTable:
    """TOML設定ファイルを型付きtableとして読み込む.

    Args:
        path (Path): UTF-8で保存されたTOML設定ファイルの絶対path.

    Returns:
        TomlTable: 構造を検証する前の最上位table.
    """
    return cast("TomlTable", tomllib.loads(path.read_text(encoding="utf-8")))


def _require_table(value: object) -> TomlTable:
    """TOML値がtableであることを検証して返す.

    Args:
        value (object): TOML parserから取得した未検証の値.

    Returns:
        TomlTable: tableとして扱える値.

    Raises:
        AssertionError: 値がTOML tableではない場合.
    """
    assert isinstance(value, dict)
    return cast("TomlTable", value)


def _require_list(value: object) -> list[object]:
    """TOML値がlistであることを検証して返す.

    Args:
        value (object): TOML parserから取得した未検証の値.

    Returns:
        list[object]: listとして扱える値.

    Raises:
        AssertionError: 値がTOML listではない場合.
    """
    assert isinstance(value, list)
    return cast("list[object]", value)


def _require_string_list(value: object) -> list[str]:
    """TOML listが文字列だけで構成されることを検証する.

    Args:
        value (object): TOML parserから取得した未検証のlist値.

    Returns:
        list[str]: 文字列だけを含むdependencyまたはrule list.

    Raises:
        AssertionError: 値がlistではないか文字列以外を含む場合.
    """
    values = _require_list(value)
    assert all(isinstance(item, str) for item in values)
    return cast("list[str]", values)


def _locked_package_versions() -> dict[str, str]:
    """uv.lockからpackage名と固定versionの対応を取得する.

    Returns:
        dict[str, str]: lockされたpackage名をversionへ対応付けたtable.

    Raises:
        AssertionError: lock内のpackage recordが期待する形ではない場合.
    """
    lock = _load_toml(UV_LOCK_PATH)
    versions: dict[str, str] = {}
    for package in _require_list(lock["package"]):
        package_table = _require_table(package)
        name = package_table.get("name")
        version = package_table.get("version")
        assert isinstance(name, str)
        if isinstance(version, str):
            versions[name] = version
    return versions


def _contains_docstring_rule(rule: str) -> bool:
    """Ruff rule selectorがdocstring rule群を指定するか判定する.

    Args:
        rule (str): Ruff設定に記録されたrule selector.

    Returns:
        bool: `D`または`DOC`のdocstring rule群を指定するときはTrue.
    """
    normalized_rule = rule.upper()
    return (
        normalized_rule == "D"
        or (normalized_rule.startswith("D") and normalized_rule[1:].isdigit())
        or normalized_rule == "DOC"
        or (normalized_rule.startswith("DOC") and normalized_rule[3:].isdigit())
    )


def _docstring_noqa_locations() -> list[str]:
    """first-party Python内のdocstring lint抑制locationを収集する.

    Returns:
        list[str]: `D`または`DOC` ruleを抑制するsource locationのlist.
    """
    locations: list[str] = []
    for root in FIRST_PARTY_PYTHON_ROOTS:
        for source_path in root.rglob("*.py"):
            for line_number, line in enumerate(
                source_path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if DOCSTRING_NOQA_PATTERN.search(line):
                    locations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{line_number}")
    return locations


def test_declares_only_active_docstring_tool_versions() -> None:
    """Activeなdocstring toolだけがdev dependencyとuv.lockに存在することを検証する.

    これはruntime dependencyへtoolが混入せず、採用を見送ったpydoclintをactiveなquality
    toolchainへ戻さない再現可能な開発環境を保証する.

    Returns:
        None: dependency宣言またはlock versionが異なる場合はassertionで失敗する.
    """
    pyproject = _load_toml(PYPROJECT_PATH)
    dependency_groups = _require_table(pyproject["dependency-groups"])
    dev_dependencies = _require_string_list(dependency_groups["dev"])
    locked_versions = _locked_package_versions()

    assert "interrogate==1.7.0" in dev_dependencies
    assert all(not dependency.startswith("pydoclint") for dependency in dev_dependencies)
    assert locked_versions["interrogate"] == "1.7.0"
    assert "pydoclint" not in locked_versions


def test_configures_non_blocking_google_docstring_toolchain() -> None:
    """RuffとinterrogateのGoogle Style対応設定を検証する.

    migration step 1ではcorpus整備前のglobal Ruff `D`有効化を禁止しつつ後続gateの
    Google conventionと全definition coverage契約を固定する.

    Returns:
        None: conventionまたはcoverage設定が期待値と異なる場合はassertionで失敗する.
    """
    pyproject = _load_toml(PYPROJECT_PATH)
    tool = _require_table(pyproject["tool"])
    ruff = _require_table(tool["ruff"])
    ruff_lint = _require_table(ruff["lint"])
    pydocstyle = _require_table(ruff_lint["pydocstyle"])
    interrogate = _require_table(tool["interrogate"])

    assert pydocstyle["convention"] == "google"
    assert not any(
        _contains_docstring_rule(rule) for rule in _require_string_list(ruff_lint["select"])
    )
    assert not any(
        _contains_docstring_rule(rule)
        for rule in _require_string_list(ruff_lint.get("extend-select", []))
    )
    assert interrogate["fail-under"] == 100
    assert interrogate["style"] == "sphinx"
    for option in (
        "ignore-init-method",
        "ignore-init-module",
        "ignore-magic",
        "ignore-module",
        "ignore-nested-functions",
        "ignore-nested-classes",
        "ignore-overloaded-functions",
        "ignore-private",
        "ignore-property-decorators",
        "ignore-setters",
        "ignore-semiprivate",
    ):
        assert interrogate[option] is False
    assert "exclude" not in interrogate
    assert "ignore-regex" not in interrogate
    assert "whitelist-regex" not in interrogate


def test_does_not_configure_deferred_pydoclint() -> None:
    """Deferredなpydoclintをactive quality gateへ設定しないことを検証する.

    Returns:
        None: pydoclintのtool設定が再導入された場合はassertionで失敗する.
    """
    pyproject = _load_toml(PYPROJECT_PATH)
    tool = _require_table(pyproject["tool"])

    assert "pydoclint" not in tool


def test_does_not_hide_docstring_debt_with_configuration_or_noqa() -> None:
    """baselineとdocstring lint抑制を使わないことを検証する.

    この検証はper-file ignoreとtool-level broad excludeを拒否し既存負債を可視化したまま
    migrationを進めることを保証する.

    Returns:
        None: 抑制設定またはsource内のdocstring `noqa`が見つかった場合はassertionで失敗する.
    """
    pyproject = _load_toml(PYPROJECT_PATH)
    tool = _require_table(pyproject["tool"])
    ruff = _require_table(tool["ruff"])
    ruff_lint = _require_table(ruff["lint"])
    per_file_ignores = _require_table(ruff_lint.get("per-file-ignores", {}))

    assert "pydoclint" not in tool
    assert all(
        not any(_contains_docstring_rule(rule) for rule in _require_string_list(ignored_rules))
        for ignored_rules in per_file_ignores.values()
    )
    assert _docstring_noqa_locations() == []


def test_docstrings_command_runs_only_active_quality_tools() -> None:
    """Docstrings commandがRuffとinterrogateだけを起動することを検証する.

    Returns:
        None: 必須toolのcommandが欠落するかpydoclintが再導入された場合はassertionで失敗する.
    """
    script = CI_SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'uv run ruff check --select D "${python_files[@]}"' in script
    assert 'uv run interrogate --config pyproject.toml "${python_files[@]}"' in script
    assert "uv run pydoclint" not in script


def test_python_files_matches_the_git_index() -> None:
    """python-filesが現worktreeのGit indexと同じPython inventoryを返すことを検証する.

    Returns:
        None: commandのexit statusまたはpathの順序と内容がindexと異なる場合はassertionで失敗する.
    """
    completed_process = _run_ci_command("python-files", cwd=PROJECT_ROOT)
    stdout = completed_process.stdout

    assert stdout is not None
    assert completed_process.returncode == 0, completed_process.stderr
    assert stdout.splitlines() == _git_indexed_python_files(PROJECT_ROOT)


def test_python_files_uses_staged_sources_from_an_isolated_git_index_despite_hook_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """python-filesがhookのGit context下でも対象一時repositoryのindexを収集することを検証する.

    Args:
        tmp_path (Path): pytestがtestごとに分離して渡す一時directory.
        monkeypatch (pytest.MonkeyPatch): hook由来のGit environmentを一時的に設定するfixture.

    Returns:
        None: staged `.py`が欠落するか、親Git contextを参照するか、`.pyi`、ignored、untracked
            pathが含まれる場合はassertionで失敗する.

    Raises:
        AssertionError: fixture fileのstagingまたはcommand実行に失敗した場合.
    """
    repository_root = tmp_path / "isolated repository"
    _initialize_temporary_git_repository(repository_root)
    _ = (repository_root / ".gitignore").write_text(
        "ignored.py\n__pycache__/\n",
        encoding="utf-8",
    )
    _ = (repository_root / "new root.py").write_text(
        '"""Staged root module."""\n',
        encoding="utf-8",
    )
    test_directory = repository_root / "tests"
    test_directory.mkdir()
    _ = (test_directory / "new test.py").write_text(
        '"""Staged test module."""\n',
        encoding="utf-8",
    )
    _ = (repository_root / "types.pyi").write_text(
        "def staged_stub() -> None: ...\n",
        encoding="utf-8",
    )
    _ = (repository_root / "ignored.py").write_text(
        '"""Ignored module."""\n',
        encoding="utf-8",
    )
    cache_directory = repository_root / "__pycache__"
    cache_directory.mkdir()
    _ = (cache_directory / "generated.py").write_text(
        '"""Generated module."""\n',
        encoding="utf-8",
    )
    _ = (repository_root / "untracked.py").write_text(
        '"""Untracked module."""\n',
        encoding="utf-8",
    )
    hook_repository_root = tmp_path / "hook parent repository"
    _initialize_temporary_git_repository(hook_repository_root)
    _ = (hook_repository_root / "parent.py").write_text(
        '"""Hook parent module."""\n',
        encoding="utf-8",
    )
    hook_staging_process = subprocess.run(
        ["git", "add", "--", "parent.py"],
        cwd=hook_repository_root,
        check=False,
        capture_output=True,
        text=True,
        env=_environment_without_git_local_context(),
    )
    hook_environment = _git_worktree_context_environment(hook_repository_root)

    assert hook_staging_process.returncode == 0, hook_staging_process.stderr
    for variable_name, value in hook_environment.items():
        monkeypatch.setenv(variable_name, value)

    staging_process = subprocess.run(
        ["git", "add", "--", "new root.py", "tests/new test.py", "types.pyi"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        env=_environment_without_git_local_context(),
    )

    assert staging_process.returncode == 0, staging_process.stderr
    completed_process = _run_ci_command("python-files", cwd=repository_root)
    stdout = completed_process.stdout

    assert stdout is not None
    assert completed_process.returncode == 0, completed_process.stderr
    assert _git_indexed_python_files(repository_root) == ["new root.py", "tests/new test.py"]
    assert stdout.splitlines() == ["new root.py", "tests/new test.py"]


def test_python_files_rejects_directories_outside_a_git_worktree(tmp_path: Path) -> None:
    """python-filesがGit worktree外ではinventoryを作成せず失敗することを検証する.

    Args:
        tmp_path (Path): Git repositoryを初期化しない一時directory.

    Returns:
        None: commandが成功するかworktree errorを報告しない場合はassertionで失敗する.
    """
    completed_process = _run_ci_command("python-files", cwd=tmp_path)

    assert completed_process.returncode != 0
    assert completed_process.stdout == ""
    assert completed_process.stderr == "python-files must be run inside a Git worktree\n"


def test_python_files_rejects_an_empty_git_index(tmp_path: Path) -> None:
    """python-filesがPython sourceを持たないGit indexを拒否することを検証する.

    Args:
        tmp_path (Path): 空のGit worktreeを作るための一時directory.

    Returns:
        None: commandが成功するかempty inventory errorを報告しない場合はassertionで失敗する.
    """
    repository_root = tmp_path / "empty repository"
    _initialize_temporary_git_repository(repository_root)
    completed_process = _run_ci_command("python-files", cwd=repository_root)

    assert completed_process.returncode != 0
    assert completed_process.stdout == ""
    assert completed_process.stderr == "Git index contains no tracked first-party Python files\n"
