"""Athena CLI packageとquality tool設定のdistribution契約を検証する."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_pyproject() -> Mapping[str, object]:
    """Repository rootのpyproject.tomlをTOML mappingとして読み込む.

    Returns:
        Mapping[str, object]: pyproject.tomlのtop-level tableを表すmapping.
    """
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())


def get_table(table: Mapping[str, object], key: str) -> Mapping[str, object]:
    """指定keyの値がTOML tableであることを検証して返す.

    Args:
        table (Mapping[str, object]): 取得元のTOML table.
        key (str): mappingから取り出すtable名.

    Returns:
        Mapping[str, object]: keyに対応するTOML subtable.
    """
    value = table[key]
    assert isinstance(value, dict)
    return cast("Mapping[str, object]", value)


def get_string_list(table: Mapping[str, object], key: str) -> Sequence[str]:
    """指定keyの値が文字列だけから成るTOML listであることを検証して返す.

    Args:
        table (Mapping[str, object]): 取得元のTOML table.
        key (str): mappingから取り出すlist名.

    Returns:
        Sequence[str]: keyに対応する文字列list.
    """
    value = table[key]
    assert isinstance(value, list)
    raw_items = cast("Sequence[object]", value)
    assert all(isinstance(item, str) for item in raw_items)
    return cast("Sequence[str]", raw_items)


def get_string(table: Mapping[str, object], key: str) -> str:
    """指定keyの値が文字列であることを検証して返す.

    Args:
        table (Mapping[str, object]): 取得元のTOML table.
        key (str): mappingから取り出す文字列key.

    Returns:
        str: keyに対応する文字列値.
    """
    value = table[key]
    assert isinstance(value, str)
    return value


def test_athena_cli_package_is_included_in_wheel() -> None:
    """Wheel build対象にAthena CLI packageが含まれることを検証する.

    Returns:
        None: package listの完全一致を検証して完了する. 呼び出し側へ値を返さない.
    """
    pyproject = load_pyproject()

    tool_config = get_table(pyproject, "tool")
    hatch_config = get_table(tool_config, "hatch")
    build_config = get_table(hatch_config, "build")
    targets_config = get_table(build_config, "targets")
    wheel_config = get_table(targets_config, "wheel")

    assert get_string_list(wheel_config, "packages") == ["src/osu_server", "src/athena_cli"]


def test_athena_console_script_points_to_cli_app() -> None:
    """Athena console scriptがCLI application entry pointを指すことを検証する.

    Returns:
        None: console script entry pointを検証して完了する. 呼び出し側へ値を返さない.
    """
    pyproject = load_pyproject()

    project_config = get_table(pyproject, "project")
    scripts_config = get_table(project_config, "scripts")

    assert get_string(scripts_config, "athena") == "athena_cli.main:main"


def test_cli_dependencies_are_declared() -> None:
    """CLI runtimeに必要なTyperとInquirerPy dependencyが宣言されることを検証する.

    Returns:
        None: dependency名の存在を検証して完了する. 呼び出し側へ値を返さない.
    """
    pyproject = load_pyproject()
    project_config = get_table(pyproject, "project")

    dependency_names = {
        dependency.split(">=", maxsplit=1)[0].lower()
        for dependency in get_string_list(project_config, "dependencies")
    }

    assert "typer" in dependency_names
    assert "inquirerpy" in dependency_names


def test_athena_cli_is_first_party_for_quality_tools() -> None:
    """Ruffとimport-linterがAthena CLIをfirst-party packageとして扱うことを検証する.

    Returns:
        None: quality toolのroot package設定を検証して完了する. 呼び出し側へ値を返さない.
    """
    pyproject = load_pyproject()

    tool_config = get_table(pyproject, "tool")
    ruff_config = get_table(tool_config, "ruff")
    ruff_lint_config = get_table(ruff_config, "lint")
    ruff_isort_config = get_table(ruff_lint_config, "isort")
    import_linter_config = get_table(tool_config, "importlinter")

    assert get_string_list(ruff_isort_config, "known-first-party") == [
        "osu_server",
        "athena_cli",
    ]
    assert get_string_list(import_linter_config, "root_packages") == [
        "osu_server",
        "athena_cli",
    ]
