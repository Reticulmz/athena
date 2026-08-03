"""Root validationがPython workspaceのtest coverageを失わないことを検証するentrypoint."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

INITIAL_WORKSPACE_MEMBERS = (
    "apps/athena_server",
    "packages/athena_crypto",
)
LEGACY_ROOT_TEST_DIRECTORY = Path("tests")
TEMPORARY_ROOT_GITLINT_TEST_PATH = LEGACY_ROOT_TEST_DIRECTORY / "unit" / "test_forbidden_words.py"
APPLICATIONS_DIRECTORY = "apps"
PACKAGES_DIRECTORY = "packages"
REPOSITORY_TOOLING_DIRECTORIES = (
    Path("tools"),
    Path("gitlint_rules"),
)
LOCKFILE_NAME = "uv.lock"
LOCKFILE_SEARCH_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".state",
        ".venv",
        "__pycache__",
        "node_modules",
        "target",
    }
)

type TomlTable = dict[str, object]


class WorkspaceValidationError(RuntimeError):
    """Workspace validation contractが満たされないことを表すexception."""


def _toml_table(value: object, name: str) -> TomlTable:
    """TOML valueがtableであることを検証する.

    Args:
        value (object): TOML parserから取得した未検証の値.
        name (str): failure messageへ表示するconfiguration field名.

    Returns:
        TomlTable: tableとして扱えるmapping.

    Raises:
        WorkspaceValidationError: valueがTOML tableではない場合.
    """
    if not isinstance(value, dict):
        message = f"{name} must be a TOML table"
        raise WorkspaceValidationError(message)
    return cast("TomlTable", value)


def _validate_authoritative_lockfile(repository_root: Path) -> None:
    """Repository内にauthoritative root lockだけが存在することを検証する.

    Args:
        repository_root (Path): `uv.lock`の探索を開始するrepository root.

    Returns:
        None: root `uv.lock`だけが存在することを確認して完了する.

    Raises:
        WorkspaceValidationError: root lockが欠落するか、source tree内に追加の`uv.lock`がある場合.
    """
    lockfile_paths: list[Path] = []
    for directory, directory_names, file_names in repository_root.walk():
        directory_names[:] = [
            name for name in directory_names if name not in LOCKFILE_SEARCH_EXCLUDED_DIRECTORIES
        ]
        if LOCKFILE_NAME in file_names:
            lockfile_paths.append(directory / LOCKFILE_NAME)

    relative_lockfile_paths = tuple(
        sorted(
            (path.relative_to(repository_root) for path in lockfile_paths),
            key=lambda path: path.as_posix(),
        )
    )
    expected_lockfile_paths = (Path(LOCKFILE_NAME),)
    if relative_lockfile_paths != expected_lockfile_paths:
        message = (
            "Workspace lockfile contract requires exactly the root uv.lock: found "
            f"{[path.as_posix() for path in relative_lockfile_paths]!r}"
        )
        raise WorkspaceValidationError(message)


def _workspace_members(repository_root: Path) -> tuple[Path, ...]:
    """Root manifestから現在許可するworkspace memberを取得する.

    Args:
        repository_root (Path): root `pyproject.toml`を所有するrepository directory.

    Returns:
        tuple[Path, ...]: rootからのrelative workspace member path.

    Raises:
        WorkspaceValidationError: member宣言が不正、初期workspace contractと異なる、member
            manifestが欠落する、またはroot lock contractが不正な場合.
    """
    manifest_path = repository_root / "pyproject.toml"
    try:
        manifest = _toml_table(
            tomllib.loads(manifest_path.read_text(encoding="utf-8")),
            "root manifest",
        )
    except FileNotFoundError as error:
        message = f"Root manifest is missing: {manifest_path}"
        raise WorkspaceValidationError(message) from error

    tool = _toml_table(manifest.get("tool"), "tool")
    uv = _toml_table(tool.get("uv"), "tool.uv")
    workspace = _toml_table(uv.get("workspace"), "tool.uv.workspace")
    raw_members = workspace.get("members")
    if not isinstance(raw_members, list):
        message = "tool.uv.workspace.members must be a string list"
        raise WorkspaceValidationError(message)
    members = cast("list[object]", raw_members)
    if not all(isinstance(member, str) for member in members):
        message = "tool.uv.workspace.members must be a string list"
        raise WorkspaceValidationError(message)

    member_paths = tuple(Path(member) for member in cast("list[str]", members))
    member_names = tuple(path.as_posix() for path in member_paths)
    if member_names != INITIAL_WORKSPACE_MEMBERS:
        message = (
            "Initial workspace members changed: expected "
            f"{list(INITIAL_WORKSPACE_MEMBERS)!r}, got {list(member_names)!r}"
        )
        raise WorkspaceValidationError(message)
    _validate_authoritative_lockfile(repository_root)
    for member_path in member_paths:
        if member_path.is_absolute() or ".." in member_path.parts:
            message = f"Workspace member must be a safe relative path: {member_path}"
            raise WorkspaceValidationError(message)
        manifest_path = repository_root / member_path / "pyproject.toml"
        if not manifest_path.is_file():
            message = f"Workspace member manifest is missing: {member_path / 'pyproject.toml'}"
            raise WorkspaceValidationError(message)
    return member_paths


def _member_kind(member_path: Path) -> str:
    """Workspace memberのownership categoryを返す.

    Args:
        member_path (Path): rootからのvalidated workspace member path.

    Returns:
        str: `application`または`package`のownership category.

    Raises:
        WorkspaceValidationError: 初期workspaceに許可されないdirectory categoryの場合.
    """
    first_component = member_path.parts[0]
    if first_component == APPLICATIONS_DIRECTORY:
        return "application"
    if first_component == PACKAGES_DIRECTORY:
        return "package"
    message = f"Workspace member has no validation owner category: {member_path}"
    raise WorkspaceValidationError(message)


def _artifact_contract_test_name(member_path: Path) -> str:
    """Workspace memberのartifact contract test filenameを返す.

    Args:
        member_path (Path): rootからのvalidated workspace member path.

    Returns:
        str: root/application pytest rootに必要なartifact test filename.
    """
    package_name = member_path.name.removeprefix("athena_").replace("-", "_")
    return f"test_{package_name}_workspace_artifact.py"


def _member_test_paths(repository_root: Path, member_path: Path) -> tuple[Path, ...]:
    """Memberのcanonical `tests` root以外へ置かれたtestを拒否する.

    Args:
        repository_root (Path): member pathを解決するrepository root.
        member_path (Path): rootからのvalidated workspace member path.

    Returns:
        tuple[Path, ...]: memberのcanonical `tests` directory内にあるtest file path.

    Raises:
        WorkspaceValidationError: canonical root外に`test_*.py`がある場合.
    """
    member_root = repository_root / member_path
    test_root = member_root / "tests"
    test_paths = tuple(sorted(path for path in member_root.rglob("test_*.py") if path.is_file()))
    invalid_paths = [
        path.relative_to(repository_root).as_posix()
        for path in test_paths
        if not path.is_relative_to(test_root)
    ]
    if invalid_paths:
        message = (
            f"Workspace member tests must live under {member_path / 'tests'}: {invalid_paths!r}"
        )
        raise WorkspaceValidationError(message)
    return test_paths


def _tooling_test_roots(repository_root: Path) -> tuple[Path, ...]:
    """Repository tooling owner配下のcanonical pytest rootを収集する.

    Args:
        repository_root (Path): tooling owner directoryを解決するrepository root.

    Returns:
        tuple[Path, ...]: `tools`と`gitlint_rules`配下で検出したroot-relative `tests` directory.

    Raises:
        WorkspaceValidationError: tooling test fileが`tests` directory外にある場合.
    """
    tooling_test_roots: list[Path] = []
    invalid_paths: list[str] = []
    for tooling_directory in REPOSITORY_TOOLING_DIRECTORIES:
        tooling_root = repository_root / tooling_directory
        owner_test_roots: set[Path] = set()
        test_paths = sorted(path for path in tooling_root.rglob("test_*.py") if path.is_file())
        for test_path in test_paths:
            test_root = next(
                (
                    parent
                    for parent in test_path.parents
                    if parent.name == "tests" and parent.is_relative_to(tooling_root)
                ),
                None,
            )
            if test_root is None:
                invalid_paths.append(test_path.relative_to(repository_root).as_posix())
                continue
            owner_test_roots.add(test_root.relative_to(repository_root))
        tooling_test_roots.extend(sorted(owner_test_roots, key=lambda path: path.as_posix()))

    if invalid_paths:
        message = (
            "Repository tooling tests must live under a canonical tests directory: "
            f"{invalid_paths!r}"
        )
        raise WorkspaceValidationError(message)
    return tuple(tooling_test_roots)


def _validate_root_test_files(repository_root: Path) -> None:
    """Root `tests`に一時Gitlint testだけが残ることを検証する.

    Args:
        repository_root (Path): root test directoryを解決するrepository root.

    Returns:
        None: `tests/unit/test_forbidden_words.py`だけが存在することを確認して完了する.

    Raises:
        WorkspaceValidationError: 一時Gitlint testが欠落するか、他のroot test fileがある場合.
    """
    legacy_test_root = repository_root / LEGACY_ROOT_TEST_DIRECTORY
    root_test_paths = tuple(
        sorted(
            path.relative_to(repository_root).as_posix()
            for path in legacy_test_root.rglob("test_*.py")
            if path.is_file()
        )
    )
    expected_root_test_paths = (TEMPORARY_ROOT_GITLINT_TEST_PATH.as_posix(),)
    if root_test_paths != expected_root_test_paths:
        message = (
            "Root test files must contain only the temporary Gitlint test: expected "
            f"{list(expected_root_test_paths)!r}, got {list(root_test_paths)!r}"
        )
        raise WorkspaceValidationError(message)


def _pytest_roots(repository_root: Path) -> tuple[Path, ...]:
    """Root gateがpytestで直接実行するtest rootを収集して検証する.

    Args:
        repository_root (Path): root manifestとtest rootを所有するrepository directory.

    Returns:
        tuple[Path, ...]: rootからのrelative pytest target directory.

    Raises:
        WorkspaceValidationError: root Gitlint testまたはtest locationが不正で、package testの
            artifact contract不足、またはpytest targetが一件もない場合.
    """
    members = _workspace_members(repository_root)
    _validate_root_test_files(repository_root)
    application_pytest_roots: list[Path] = []

    artifact_contract_test_names: list[str] = []
    for member_path in members:
        test_paths = _member_test_paths(repository_root, member_path)
        test_root = member_path / "tests"
        if _member_kind(member_path) == "application" and test_paths:
            application_pytest_roots.append(test_root)
        artifact_contract_test_names.append(_artifact_contract_test_name(member_path))

    if not application_pytest_roots:
        message = "No application pytest test directories were discovered"
        raise WorkspaceValidationError(message)

    pytest_test_files = {
        path.name
        for pytest_root in application_pytest_roots
        for path in (repository_root / pytest_root).rglob("test_*.py")
        if path.is_file()
    }
    missing_contract_tests = sorted(
        test_name
        for test_name in artifact_contract_test_names
        if test_name not in pytest_test_files
    )
    if missing_contract_tests:
        message = (
            "Workspace artifacts are not covered by an installed artifact contract test: "
            f"{missing_contract_tests!r}"
        )
        raise WorkspaceValidationError(message)
    return (
        LEGACY_ROOT_TEST_DIRECTORY,
        *application_pytest_roots,
        *_tooling_test_roots(repository_root),
    )


def _type_check_paths(
    repository_root: Path,
    pytest_roots: tuple[Path, ...],
) -> tuple[Path, ...]:
    """Root Basedpyrightが検査するworkspaceとrepository toolingのpathを返す.

    Args:
        repository_root (Path): workspace memberを解決するrepository root.
        pytest_roots (tuple[Path, ...]): validation済みroot pytest target directory.

    Returns:
        tuple[Path, ...]: source、root/server test、public typing、repository toolingを一度ずつ含む
            type target.
    """
    application_type_paths: list[Path] = []
    package_type_paths: list[Path] = []
    for member_path in _workspace_members(repository_root):
        if _member_kind(member_path) == "application":
            application_type_paths.extend((member_path / "src", member_path / "scripts"))
        else:
            package_type_paths.extend(
                (
                    member_path / "typings",
                    member_path / "scripts",
                    member_path / "tests",
                )
            )

    application_test_paths = [
        pytest_root
        for pytest_root in pytest_roots
        if pytest_root.parts[0] == APPLICATIONS_DIRECTORY
    ]
    root_test_paths = [
        pytest_root for pytest_root in pytest_roots if pytest_root == LEGACY_ROOT_TEST_DIRECTORY
    ]
    return tuple(
        dict.fromkeys(
            (
                *application_type_paths,
                *root_test_paths,
                *application_test_paths,
                *package_type_paths,
                *REPOSITORY_TOOLING_DIRECTORIES,
            )
        )
    )


def _run_basedpyright(repository_root: Path, type_check_paths: tuple[Path, ...]) -> int:
    """Validation済みinventoryに対してBasedpyrightを実行する.

    Args:
        repository_root (Path): type checkerを実行するrepository root.
        type_check_paths (tuple[Path, ...]): root-relative Basedpyright target directory.

    Returns:
        int: Basedpyright processのexit status. 実行不能な場合は1.
    """
    command = (
        "uv",
        "run",
        "basedpyright",
        *(path.as_posix() for path in type_check_paths),
    )
    try:
        completed_process = subprocess.run(command, cwd=repository_root, check=False)
    except OSError as error:
        print(f"Workspace type check failed: {error}", file=sys.stderr)
        return 1
    return completed_process.returncode


def _parser() -> argparse.ArgumentParser:
    """Workspace validation CLIのargument parserを作る.

    Returns:
        argparse.ArgumentParser: pytest/type targetの出力とtype check実行を受け付けるparser.
            repository root overrideも受け付ける.
    """
    parser = argparse.ArgumentParser(
        description="Verify root workspace test coverage before running pytest.",
    )
    _ = parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Root pyproject.tomlを所有するrepository directory.",
    )
    output_mode = parser.add_mutually_exclusive_group()
    _ = output_mode.add_argument(
        "--pytest-paths",
        action="store_true",
        help="検証済みpytest targetをroot-relative pathで一行ずつ出力する.",
    )
    _ = output_mode.add_argument(
        "--type-check-paths",
        action="store_true",
        help="検証済みBasedpyright targetをroot-relative pathで一行ずつ出力する.",
    )
    _ = output_mode.add_argument(
        "--run-basedpyright",
        action="store_true",
        help="検証済みBasedpyright targetにtype checkを実行する.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Workspace validation inventoryを検証し、pytest/type checkを実行または報告する.

    Args:
        argv (Sequence[str] | None): parse対象のCLI argument. Noneの場合はprocess argumentを使う.

    Returns:
        int: contractまたは要求されたtype checkが成功する場合は0、それ以外は1.
    """
    arguments = _parser().parse_args(argv)
    repository_root = cast("Path", arguments.repository_root).resolve()
    print_pytest_paths = cast("bool", arguments.pytest_paths)
    print_type_check_paths = cast("bool", arguments.type_check_paths)
    run_basedpyright = cast("bool", arguments.run_basedpyright)
    try:
        pytest_roots = _pytest_roots(repository_root)
        type_check_paths = (
            _type_check_paths(repository_root, pytest_roots)
            if print_type_check_paths or run_basedpyright
            else ()
        )
    except WorkspaceValidationError as error:
        print(f"Workspace validation failed: {error}", file=sys.stderr)
        return 1

    if print_pytest_paths:
        for pytest_root in pytest_roots:
            print(pytest_root.as_posix())
    elif print_type_check_paths:
        for type_check_path in type_check_paths:
            print(type_check_path.as_posix())
    elif run_basedpyright:
        return _run_basedpyright(repository_root, type_check_paths)
    else:
        print("workspace validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
