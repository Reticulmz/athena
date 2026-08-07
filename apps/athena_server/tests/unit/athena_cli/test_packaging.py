"""Athena server workspaceとroot orchestrationのdistribution契約を検証する."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[5]
SERVER_WORKSPACE_ROOT = PROJECT_ROOT / "apps" / "athena_server"
ROOT_MANIFEST_PATH = PROJECT_ROOT / "pyproject.toml"
SERVER_MANIFEST_PATH = SERVER_WORKSPACE_ROOT / "pyproject.toml"
RUNTIME_DEPENDENCIES = [
    "starlette",
    "uvicorn",
    "pydantic-settings",
    "sqlalchemy[asyncio]",
    "asyncpg",
    "alembic",
    "valkey-glide>=2.1",
    "argon2-cffi",
    "caterpillar-py>=2.8.1",
    "httpx>=0.28.1",
    "python-multipart>=0.0.29",
    "structlog>=25.5.0",
    "taskiq>=0.11",
    "taskiq-redis>=1.0",
    "typer>=0.26.7",
    "inquirerpy>=0.3.4",
    "athena-crypto",
    "dishka",
    "starlette-dishka",
    "rosu-pp-py==4.0.2",
]


def load_manifest(manifest_path: Path) -> Mapping[str, object]:
    """指定したpyproject.tomlをTOML mappingとして読み込む.

    Args:
        manifest_path (Path): 読み込むworkspace manifestのpath.

    Returns:
        Mapping[str, object]: manifestのtop-level tableを表すmapping.
    """
    return tomllib.loads(manifest_path.read_text(encoding="utf-8"))


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


def test_root_manifest_is_virtual_uv_workspace() -> None:
    """Rootがdistribution metadataを持たないsingle-lock uv workspaceであることを検証する.

    Serverとcryptoをmemberとして列挙し、root自身はproject、build backend、console scriptを
    所有しないことで同名distributionの二重ownershipを防ぐ.

    Returns:
        None: root virtual workspaceのobservable manifest contractを検証して完了する.
    """
    root_manifest = load_manifest(ROOT_MANIFEST_PATH)
    tool_config = get_table(root_manifest, "tool")
    uv_config = get_table(tool_config, "uv")
    workspace_config = get_table(uv_config, "workspace")

    assert "project" not in root_manifest
    assert "build-system" not in root_manifest
    assert uv_config["package"] is False
    assert get_string_list(workspace_config, "members") == [
        "apps/athena_server",
        "packages/athena_crypto",
    ]


def test_server_manifest_owns_single_athena_distribution() -> None:
    """Server workspaceが既存Athena distribution metadataを単独所有することを検証する.

    Runtime dependency、namespace、console entrypoint、Hatchling build metadataを同じmanifestへ
    集約し、root distributionへのfallbackが不要であることを確認する.

    Returns:
        None: server distribution metadataの完全な移管を検証して完了する.
    """
    server_manifest = load_manifest(SERVER_MANIFEST_PATH)
    project_config = get_table(server_manifest, "project")
    scripts_config = get_table(project_config, "scripts")
    build_system_config = get_table(server_manifest, "build-system")
    tool_config = get_table(server_manifest, "tool")
    hatch_config = get_table(tool_config, "hatch")
    build_config = get_table(hatch_config, "build")
    targets_config = get_table(build_config, "targets")
    wheel_config = get_table(targets_config, "wheel")

    assert get_string(project_config, "name") == "athena"
    assert get_string(project_config, "version") == "0.1.0"
    assert get_string_list(project_config, "dependencies") == RUNTIME_DEPENDENCIES
    assert get_string(scripts_config, "athena") == "athena_cli.main:main"
    assert get_string(build_system_config, "build-backend") == "hatchling.build"
    assert get_string_list(wheel_config, "packages") == ["src/osu_server", "src/athena_cli"]
    force_include_config = get_table(wheel_config, "force-include")
    assert force_include_config == {
        "alembic.ini": "alembic.ini",
        "alembic": "alembic",
    }


def test_server_source_and_lock_have_single_canonical_owner() -> None:
    """Server sourceとPython lockがlegacy rootまたはmemberへ複製されないことを検証する.

    Returns:
        None: namespace sourceのphysical ownerとauthoritative lockの一意性を検証して完了する.
    """
    assert (SERVER_WORKSPACE_ROOT / "src" / "osu_server" / "__init__.py").is_file()
    assert (SERVER_WORKSPACE_ROOT / "src" / "athena_cli" / "__init__.py").is_file()
    assert not (PROJECT_ROOT / "src").exists()
    assert (PROJECT_ROOT / "uv.lock").is_file()
    assert not (SERVER_WORKSPACE_ROOT / "uv.lock").exists()
    assert not (PROJECT_ROOT / "packages" / "athena_crypto" / "uv.lock").exists()


def test_server_manifest_owns_cli_import_boundary() -> None:
    """Server manifestがCLIからserverへの一方向dependencyを機械検証することを確認する.

    `osu_server -> athena_cli`を禁止するcontractをserver ownerに置く. root Ruff policyは
    両namespaceをfirst-partyとして解決することを検証する.

    Returns:
        None: import-linter contractとroot quality policyのowner分離を検証して完了する.
    """
    root_manifest = load_manifest(ROOT_MANIFEST_PATH)
    root_tool_config = get_table(root_manifest, "tool")
    ruff_config = get_table(root_tool_config, "ruff")
    ruff_lint_config = get_table(ruff_config, "lint")
    ruff_isort_config = get_table(ruff_lint_config, "isort")

    server_manifest = load_manifest(SERVER_MANIFEST_PATH)
    server_tool_config = get_table(server_manifest, "tool")
    import_linter_config = get_table(server_tool_config, "importlinter")
    raw_contracts = import_linter_config["contracts"]
    assert isinstance(raw_contracts, list)
    contracts = cast("Sequence[Mapping[str, object]]", raw_contracts)
    runtime_contract = next(
        contract
        for contract in contracts
        if contract.get("name") == "Server runtime doesn't depend on CLI"
    )

    assert get_string_list(ruff_isort_config, "known-first-party") == [
        "osu_server",
        "athena_cli",
    ]
    assert get_string_list(import_linter_config, "root_packages") == [
        "osu_server",
        "athena_cli",
    ]
    assert get_string_list(runtime_contract, "source_modules") == ["osu_server"]
    assert get_string_list(runtime_contract, "forbidden_modules") == ["athena_cli"]


def test_root_validation_uses_server_workspace_paths() -> None:
    """Root validation実装が検証済みworkspace inventoryを型検査することを検証する.

    Canonical Just recipeが利用するroot-owned libraryは、存在しないlegacy `src/`やroot
    import-linter configへfallbackせず、server/cryptoとrepository toolingをdynamic verifierの
    inventoryからBasedpyrightへ渡す.

    Returns:
        None: Canonical quality implementationのworkspace pathを検証して完了する.
    """
    root_manifest = load_manifest(ROOT_MANIFEST_PATH)
    root_tool_config = get_table(root_manifest, "tool")
    basedpyright_config = get_table(root_tool_config, "basedpyright")
    quality_library = (
        PROJECT_ROOT / "tools" / "monorepo_migration" / "repository_validation.sh"
    ).read_text(encoding="utf-8")
    workspace_validation_tool = (
        PROJECT_ROOT / "tools" / "monorepo_migration" / "verify_workspace_validation.py"
    )
    expected_type_check_paths = [
        "apps/athena_server/src",
        "apps/athena_server/scripts",
        "apps/athena_server/tests",
        "packages/athena_crypto/typings",
        "packages/athena_crypto/scripts",
        "packages/athena_crypto/tests",
        "tools/monorepo_migration",
        "tools/gitlint",
    ]

    assert "tools/monorepo_migration/verify_workspace_validation.py" in quality_library
    assert "uv run lint-imports --config apps/athena_server/pyproject.toml" in quality_library
    type_check_command_start = quality_library.index(
        "uv run python tools/monorepo_migration/verify_workspace_validation.py",
    )
    type_check_command = quality_library[
        type_check_command_start : quality_library.index(
            'echo "--> Import linter"',
            type_check_command_start,
        )
    ]
    assert "--run-basedpyright" in type_check_command
    assert get_string_list(basedpyright_config, "extraPaths") == [
        "apps/athena_server/src",
        "apps/athena_server",
    ]

    inventory_result = subprocess.run(
        [sys.executable, str(workspace_validation_tool), "--type-check-paths"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert inventory_result.returncode == 0, inventory_result.stderr
    assert inventory_result.stdout.splitlines() == expected_type_check_paths
    assert (PROJECT_ROOT / "tools/gitlint/rules/forbidden_words.py").is_file()
    assert (PROJECT_ROOT / "tools/gitlint/tests/test_forbidden_words.py").is_file()
    assert not any((PROJECT_ROOT / "tests").rglob("test_*.py"))
    assert not any((PROJECT_ROOT / "gitlint_rules").rglob("*.py"))
