"""Root validationがPython workspaceのtest coverageを失わないことを検証するentrypoint."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

INITIAL_WORKSPACE_MEMBERS = (
    "apps/athena_server",
    "packages/athena_crypto",
)
APPLICATIONS_DIRECTORY = "apps"
PACKAGES_DIRECTORY = "packages"
REPOSITORY_TOOLING_ROOT = Path("tools")
REPOSITORY_TOOLING_OWNERS = (
    REPOSITORY_TOOLING_ROOT / "monorepo_migration",
    REPOSITORY_TOOLING_ROOT / "gitlint",
)
LOCKFILE_NAME = "uv.lock"
SEARCH_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".state",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
    }
)

type TomlTable = dict[str, object]


@dataclass(frozen=True, slots=True)
class PackageTestContract:
    """Package testをisolated artifact verifierから実行するroot contractを表す.

    Attributes:
        test_root (Path): Package ownerが保持するtest source directory.
        verifier (Path): Wheel-only consumerでpackage testを実行するentrypoint.
        root_contract_test (Path): Direct pytest targetからverifierを一度だけ実行するtest file.
    """

    test_root: Path
    verifier: Path
    root_contract_test: Path


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
            name for name in directory_names if name not in SEARCH_EXCLUDED_DIRECTORIES
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


def _tooling_test_inventory(
    repository_root: Path,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """明示されたrepository tooling ownerのtest rootとtest fileを収集する.

    Args:
        repository_root (Path): tooling owner directoryを解決するrepository root.

    Returns:
        tuple[tuple[Path, ...], tuple[Path, ...]]: ownerごとのroot-relative `tests` directoryと、
            その配下で検出したtest file path.

    Raises:
        WorkspaceValidationError: owner testが欠落するか、`tests` directory外にある場合.
    """
    tooling_test_roots: list[Path] = []
    tooling_test_paths: list[Path] = []
    invalid_paths: list[str] = []
    for tooling_owner in REPOSITORY_TOOLING_OWNERS:
        tooling_root = repository_root / tooling_owner
        canonical_test_root = tooling_root / "tests"
        test_paths = sorted(path for path in tooling_root.rglob("test_*.py") if path.is_file())
        invalid_paths.extend(
            test_path.relative_to(repository_root).as_posix()
            for test_path in test_paths
            if not test_path.is_relative_to(canonical_test_root)
        )
        if not test_paths:
            message = f"Repository tooling owner has no tests: {tooling_owner}"
            raise WorkspaceValidationError(message)
        tooling_test_roots.append(canonical_test_root.relative_to(repository_root))
        tooling_test_paths.extend(test_paths)

    if invalid_paths:
        message = (
            "Repository tooling tests must live under a canonical tests directory: "
            f"{invalid_paths!r}"
        )
        raise WorkspaceValidationError(message)
    return tuple(tooling_test_roots), tuple(tooling_test_paths)


def _all_test_paths(repository_root: Path) -> tuple[Path, ...]:
    """Generated stateを除くrepository treeからPython test fileを収集する.

    Args:
        repository_root (Path): test fileの探索を開始するrepository root.

    Returns:
        tuple[Path, ...]: rootからのrelative path順に並べた全test file.
    """
    test_paths: list[Path] = []
    for directory, directory_names, file_names in repository_root.walk():
        directory_names[:] = [
            name for name in directory_names if name not in SEARCH_EXCLUDED_DIRECTORIES
        ]
        test_paths.extend(
            (directory / file_name).relative_to(repository_root)
            for file_name in file_names
            if file_name.startswith("test_") and file_name.endswith(".py")
        )
    return tuple(sorted(test_paths, key=lambda path: path.as_posix()))


def _validate_test_ownership(repository_root: Path, owned_test_paths: set[Path]) -> None:
    """全test fileが明示されたworkspaceまたはtool ownerに属することを検証する.

    Args:
        repository_root (Path): repository全体のtest inventoryを解決するroot directory.
        owned_test_paths (set[Path]): owner policyから収集したroot-relative test file path.

    Returns:
        None: 全test fileのownerが明示されていることを確認して完了する.

    Raises:
        WorkspaceValidationError: root gateへ接続されていないtest locationが存在する場合.
    """
    unowned_test_paths = [
        path.as_posix()
        for path in _all_test_paths(repository_root)
        if path not in owned_test_paths
    ]
    if unowned_test_paths:
        message = f"Test files have no root validation owner: {unowned_test_paths!r}"
        raise WorkspaceValidationError(message)


def _configured_pytest_paths(repository_root: Path) -> tuple[Path, ...]:
    """Root manifestが公開するpytest target pathを取得する.

    Args:
        repository_root (Path): root `pyproject.toml`を所有するrepository directory.

    Returns:
        tuple[Path, ...]: root manifestに宣言された順序付きpytest target path.

    Raises:
        WorkspaceValidationError: pytest設定またはtestpathsが不正な場合.
    """
    manifest_path = repository_root / "pyproject.toml"
    manifest = _toml_table(
        tomllib.loads(manifest_path.read_text(encoding="utf-8")),
        "root manifest",
    )
    tool = _toml_table(manifest.get("tool"), "tool")
    pytest_configuration = _toml_table(tool.get("pytest"), "tool.pytest")
    ini_options = _toml_table(
        pytest_configuration.get("ini_options"),
        "tool.pytest.ini_options",
    )
    raw_testpaths = ini_options.get("testpaths")
    if not isinstance(raw_testpaths, list):
        message = "tool.pytest.ini_options.testpaths must be a string list"
        raise WorkspaceValidationError(message)
    testpaths = cast("list[object]", raw_testpaths)
    if not all(isinstance(testpath, str) for testpath in testpaths):
        message = "tool.pytest.ini_options.testpaths must be a string list"
        raise WorkspaceValidationError(message)
    return tuple(Path(testpath) for testpath in cast("list[str]", raw_testpaths))


def _toml_string(table: TomlTable, field_name: str, context: str) -> str:
    """TOML tableから必須string fieldを取得する.

    Args:
        table (TomlTable): fieldを取得するconfiguration table.
        field_name (str): 取得するfield名.
        context (str): failure messageに含めるtableの識別名.

    Returns:
        str: 検証済みconfiguration value.

    Raises:
        WorkspaceValidationError: fieldがstringでない場合.
    """
    value = table.get(field_name)
    if not isinstance(value, str):
        message = f"{context}.{field_name} must be a string"
        raise WorkspaceValidationError(message)
    return value


def _safe_contract_path(raw_path: str, field_name: str) -> Path:
    """Package test contract pathがrepository-relativeであることを検証する.

    Args:
        raw_path (str): Root configurationから取得したpath value.
        field_name (str): failure messageに含めるconfiguration field名.

    Returns:
        Path: 安全なrelative pathとして扱えるpath.

    Raises:
        WorkspaceValidationError: absolute pathまたはparent traversalを含む場合.
    """
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        message = f"{field_name} must be a safe repository-relative path: {raw_path}"
        raise WorkspaceValidationError(message)
    return path


def _package_test_contracts(
    repository_root: Path,
    member_paths: tuple[Path, ...],
    application_pytest_roots: tuple[Path, ...],
) -> tuple[PackageTestContract, ...]:
    """Package-owned testをdirect pytest以外から実行するcontractを検証する.

    Args:
        repository_root (Path): Root policyとcontract artifactを解決するrepository root.
        member_paths (tuple[Path, ...]): Validation済みworkspace member path.
        application_pytest_roots (tuple[Path, ...]): Root gateが直接実行するapplication test root.

    Returns:
        tuple[PackageTestContract, ...]: Package member順のartifact test execution contract.

    Raises:
        WorkspaceValidationError: Package test contractが欠落、不正、またはowner外を参照する場合.
    """
    manifest = _toml_table(
        tomllib.loads((repository_root / "pyproject.toml").read_text(encoding="utf-8")),
        "root manifest",
    )
    tool = _toml_table(manifest.get("tool"), "tool")
    athena = _toml_table(tool.get("athena", {}), "tool.athena")
    validation = _toml_table(
        athena.get("validation", {}),
        "tool.athena.validation",
    )
    package_tests = _toml_table(
        validation.get("package-tests", {}),
        "tool.athena.validation.package-tests",
    )
    package_members = tuple(
        member_path for member_path in member_paths if _member_kind(member_path) == "package"
    )
    expected_test_roots = tuple(member_path / "tests" for member_path in package_members)
    configured_test_roots = tuple(Path(test_root) for test_root in package_tests)
    if configured_test_roots != expected_test_roots:
        message = (
            "Package test execution contracts must match package workspace owners: expected "
            f"{[path.as_posix() for path in expected_test_roots]!r}, got "
            f"{[path.as_posix() for path in configured_test_roots]!r}"
        )
        raise WorkspaceValidationError(message)

    contracts: list[PackageTestContract] = []
    for member_path, test_root in zip(package_members, expected_test_roots, strict=True):
        context = f"tool.athena.validation.package-tests.{test_root.as_posix()}"
        configuration = _toml_table(package_tests.get(test_root.as_posix()), context)
        verifier = _safe_contract_path(
            _toml_string(configuration, "verifier", context),
            f"{context}.verifier",
        )
        root_contract_test = _safe_contract_path(
            _toml_string(configuration, "root-contract-test", context),
            f"{context}.root-contract-test",
        )
        expected_contract_name = _artifact_contract_test_name(member_path)
        if (
            verifier.parent != member_path / "scripts"
            or not (repository_root / verifier).is_file()
        ):
            message = f"Package artifact verifier is missing or outside its owner: {verifier}"
            raise WorkspaceValidationError(message)
        if root_contract_test.name != expected_contract_name or not any(
            root_contract_test.is_relative_to(pytest_root)
            for pytest_root in application_pytest_roots
        ):
            message = (
                "Package root contract test must be an application pytest target named "
                f"{expected_contract_name}: {root_contract_test}"
            )
            raise WorkspaceValidationError(message)
        if not (repository_root / root_contract_test).is_file():
            message = f"Package root contract test is missing: {root_contract_test}"
            raise WorkspaceValidationError(message)
        contracts.append(
            PackageTestContract(
                test_root=test_root,
                verifier=verifier,
                root_contract_test=root_contract_test,
            )
        )
    return tuple(contracts)


def _pytest_roots(repository_root: Path) -> tuple[Path, ...]:
    """Root gateがpytestで直接実行するtest rootを収集して検証する.

    Args:
        repository_root (Path): root manifestとtest rootを所有するrepository directory.

    Returns:
        tuple[Path, ...]: rootからのrelative pytest target directory.

    Raises:
        WorkspaceValidationError: test ownershipまたはroot pytest設定が不正で、package testの
            artifact contract不足、またはpytest targetが一件もない場合.
    """
    members = _workspace_members(repository_root)
    application_pytest_roots: list[Path] = []
    owned_test_paths: set[Path] = set()

    artifact_contract_test_names: list[str] = []
    for member_path in members:
        test_paths = _member_test_paths(repository_root, member_path)
        if not test_paths:
            message = f"Workspace member has no tests: {member_path}"
            raise WorkspaceValidationError(message)
        owned_test_paths.update(path.relative_to(repository_root) for path in test_paths)
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
    _ = _package_test_contracts(
        repository_root,
        members,
        tuple(application_pytest_roots),
    )
    tooling_test_roots, tooling_test_paths = _tooling_test_inventory(repository_root)
    owned_test_paths.update(path.relative_to(repository_root) for path in tooling_test_paths)
    _validate_test_ownership(repository_root, owned_test_paths)
    pytest_roots = (*application_pytest_roots, *tooling_test_roots)
    configured_pytest_paths = _configured_pytest_paths(repository_root)
    if configured_pytest_paths != pytest_roots:
        message = (
            "Root pytest testpaths must match validation owners: expected "
            f"{[path.as_posix() for path in pytest_roots]!r}, got "
            f"{[path.as_posix() for path in configured_pytest_paths]!r}"
        )
        raise WorkspaceValidationError(message)
    return pytest_roots


def _test_coverage_lines(
    repository_root: Path,
    pytest_roots: tuple[Path, ...],
) -> tuple[str, ...]:
    """Root test gateが各ownerを実行する方法を順序付きで報告する.

    Args:
        repository_root (Path): Workspaceとpackage contractを解決するrepository root.
        pytest_roots (tuple[Path, ...]): Validation済みdirect pytest target.

    Returns:
        tuple[str, ...]: Server、crypto、repository toolごとのtest execution contract.
    """
    members = _workspace_members(repository_root)
    application_pytest_roots = tuple(
        pytest_root
        for pytest_root in pytest_roots
        if pytest_root.parts[0] == APPLICATIONS_DIRECTORY
    )
    package_contracts = {
        contract.test_root: contract
        for contract in _package_test_contracts(
            repository_root,
            members,
            application_pytest_roots,
        )
    }
    coverage_lines: list[str] = []
    for member_path in members:
        test_root = member_path / "tests"
        if _member_kind(member_path) == "application":
            coverage_lines.append(f"{test_root.as_posix()}: pytest")
            continue
        contract = package_contracts[test_root]
        verifier = contract.verifier.as_posix()
        root_contract_test = contract.root_contract_test.as_posix()
        execution_contract = ", ".join(
            (
                f"artifact-verifier={verifier}",
                f"root-contract-test={root_contract_test}",
            )
        )
        coverage_lines.append(f"{test_root.as_posix()}: {execution_contract}")
    coverage_lines.extend(
        f"{pytest_root.as_posix()}: pytest"
        for pytest_root in pytest_roots
        if pytest_root.parts[0] == REPOSITORY_TOOLING_ROOT.name
    )
    return tuple(coverage_lines)


def _type_check_paths(
    repository_root: Path,
    pytest_roots: tuple[Path, ...],
) -> tuple[Path, ...]:
    """Root Basedpyrightが検査するworkspaceとrepository toolingのpathを返す.

    Args:
        repository_root (Path): workspace memberを解決するrepository root.
        pytest_roots (tuple[Path, ...]): validation済みroot pytest target directory.

    Returns:
        tuple[Path, ...]: source、workspace test、public typing、repository toolingを一度ずつ含む
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
    return tuple(
        dict.fromkeys(
            (
                *application_type_paths,
                *application_test_paths,
                *package_type_paths,
                *REPOSITORY_TOOLING_OWNERS,
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
        "--test-coverage",
        action="store_true",
        help="各workspace/tool test ownerのdirectまたはartifact execution contractを出力する.",
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
    print_test_coverage = cast("bool", arguments.test_coverage)
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
    elif print_test_coverage:
        for coverage_line in _test_coverage_lines(repository_root, pytest_roots):
            print(coverage_line)
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
