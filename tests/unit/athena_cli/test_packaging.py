from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def load_pyproject() -> Mapping[str, object]:
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())


def get_table(table: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = table[key]
    assert isinstance(value, dict)
    return cast("Mapping[str, object]", value)


def get_string_list(table: Mapping[str, object], key: str) -> Sequence[str]:
    value = table[key]
    assert isinstance(value, list)
    raw_items = cast("Sequence[object]", value)
    assert all(isinstance(item, str) for item in raw_items)
    return cast("Sequence[str]", raw_items)


def get_string(table: Mapping[str, object], key: str) -> str:
    value = table[key]
    assert isinstance(value, str)
    return value


def test_athena_cli_package_is_included_in_wheel() -> None:
    pyproject = load_pyproject()

    tool_config = get_table(pyproject, "tool")
    hatch_config = get_table(tool_config, "hatch")
    build_config = get_table(hatch_config, "build")
    targets_config = get_table(build_config, "targets")
    wheel_config = get_table(targets_config, "wheel")

    assert get_string_list(wheel_config, "packages") == ["src/osu_server", "src/athena_cli"]


def test_athena_console_script_points_to_cli_app() -> None:
    pyproject = load_pyproject()

    project_config = get_table(pyproject, "project")
    scripts_config = get_table(project_config, "scripts")

    assert get_string(scripts_config, "athena") == "athena_cli.main:main"


def test_cli_dependencies_are_declared() -> None:
    pyproject = load_pyproject()
    project_config = get_table(pyproject, "project")

    dependency_names = {
        dependency.split(">=", maxsplit=1)[0].lower()
        for dependency in get_string_list(project_config, "dependencies")
    }

    assert "typer" in dependency_names
    assert "inquirerpy" in dependency_names


def test_athena_cli_is_first_party_for_quality_tools() -> None:
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
