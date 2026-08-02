"""Frontend workspaceを必要としないAthena server workspaceの操作を提供するentrypoint."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

SERVER_WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVER_WORKSPACE_ROOT.parents[1]
SERVER_SOURCE_PATHS = (
    SERVER_WORKSPACE_ROOT / "src",
    SERVER_WORKSPACE_ROOT / "scripts",
)
SERVER_ARTIFACT_TEST_PATH = (
    REPOSITORY_ROOT / "tests" / "unit" / "test_server_workspace_artifact.py"
)


def _run(command: Sequence[str]) -> None:
    """Server workspace operationをrepository rootから実行する.

    Args:
        command (Sequence[str]): shellを介さず実行するprogramとargumentの並び.

    Returns:
        None: commandが成功した後、呼び出し側へ値を返さずに完了する.

    Raises:
        RuntimeError: commandがnon-zero exit statusで終了した場合.
    """
    completed_process = subprocess.run(command, cwd=REPOSITORY_ROOT, check=False)
    if completed_process.returncode != 0:
        command_text = " ".join(command)
        message = (
            f"Server workspace operation failed ({completed_process.returncode}): {command_text}"
        )
        raise RuntimeError(message)


def _sync() -> None:
    """Authoritative root lockからserver workspaceのdependencyを同期する.

    Returns:
        None: serverとcryptoを含むlocked dependency environmentを同期して完了する.
    """
    _run(
        (
            "uv",
            "sync",
            "--project",
            str(SERVER_WORKSPACE_ROOT),
            "--locked",
            "--all-groups",
        )
    )


def _build(output_directory: Path) -> None:
    """Server workspace wheelを指定directoryへbuildする.

    Args:
        output_directory (Path): buildしたwheelを格納するdirectory.

    Returns:
        None: Athena server wheelを一つ生成して完了する.

    Raises:
        RuntimeError: wheelが生成されないか複数生成された場合.
    """
    output_directory.mkdir(parents=True, exist_ok=True)
    _run(
        (
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(output_directory),
            str(SERVER_WORKSPACE_ROOT),
        )
    )
    wheels = tuple(output_directory.glob("athena-*.whl"))
    if len(wheels) != 1:
        message = f"Expected exactly one Athena server wheel, got {wheels!r}"
        raise RuntimeError(message)


def _quality() -> None:
    """Server sourceとowner scriptへformat、lint、docstring、type、import検査を実行する.

    Returns:
        None: server workspaceのquality operationを成功させて完了する.
    """
    source_paths = tuple(str(path) for path in SERVER_SOURCE_PATHS)
    for command in (
        ("ruff", "format", "--check", *source_paths),
        ("ruff", "check", *source_paths),
        ("interrogate", "--config", str(REPOSITORY_ROOT / "pyproject.toml"), *source_paths),
        ("basedpyright", *source_paths),
        (
            "lint-imports",
            "--config",
            str(SERVER_WORKSPACE_ROOT / "pyproject.toml"),
        ),
    ):
        _run(("uv", "run", "--project", str(SERVER_WORKSPACE_ROOT), "--locked", *command))


def _test() -> None:
    """Current server ownerが提供するinstalled-artifact testを実行する.

    Task 2.1でserver test全体がworkspaceへ移設されるまで、server-owned wheel contractをroot test
    catalogから実行する。このtestはsource checkoutへのfallbackなしでapp、worker、CLIを検証する.

    Returns:
        None: server installed-artifact testが成功して完了する.
    """
    _run(
        (
            "uv",
            "run",
            "--project",
            str(SERVER_WORKSPACE_ROOT),
            "--locked",
            "pytest",
            str(SERVER_ARTIFACT_TEST_PATH),
            "-q",
        )
    )


def _parser() -> argparse.ArgumentParser:
    """Server workspace operationを選択するargument parserを作る.

    Returns:
        argparse.ArgumentParser: operationとbuild output directoryを受け付けるparser.
    """
    parser = argparse.ArgumentParser(
        description="Run one Athena server workspace operation without a frontend member.",
    )
    _ = parser.add_argument(
        "operation",
        choices=("sync", "build", "quality", "test"),
        help="実行するserver workspace operation.",
    )
    _ = parser.add_argument(
        "--output-directory",
        type=Path,
        help="build operationがwheelを出力するdirectory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """選択したserver workspace operationを実行する.

    Args:
        argv (Sequence[str] | None): parse対象のCLI argument. Noneの場合はprocess argumentを使う.

    Returns:
        int: operationが成功した場合は0、inputまたはoperationが不正な場合は1.
    """
    arguments = _parser().parse_args(argv)
    operation = cast("str", arguments.operation)
    output_directory = cast("Path | None", arguments.output_directory)
    if operation == "sync":
        _sync()
    elif operation == "build":
        if output_directory is None:
            print("--output-directory is required for build", file=sys.stderr)
            return 1
        _build(output_directory.resolve())
    elif operation == "quality":
        _quality()
    else:
        _test()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
