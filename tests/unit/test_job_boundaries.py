"""worker job boundary の回帰契約を検証する."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

import osu_server.infrastructure.jobs as infrastructure_jobs
import osu_server.jobs as application_jobs

PROJECT_ROOT = Path(__file__).parents[2]
SERVER_WORKSPACE_ROOT = PROJECT_ROOT / "apps" / "athena_server"
PYPROJECT_PATH = SERVER_WORKSPACE_ROOT / "pyproject.toml"

type TomlTable = dict[str, object]


def load_pyproject() -> TomlTable:
    """境界 contract 用に pyproject.toml を読み込む.

    Returns:
        TomlTable: TOML 解析結果の最上位 table.
    """
    return cast("TomlTable", tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8")))


def require_table(value: object) -> TomlTable:
    """値が TOML table であることを検証して返す.

    Args:
        value (object): TOML 解析結果から取得した値.

    Returns:
        TomlTable: table として扱える値.
    """
    assert isinstance(value, dict)
    return cast("TomlTable", value)


def require_list(value: object) -> list[object]:
    """値が TOML list であることを検証して返す.

    Args:
        value (object): TOML 解析結果から取得した値.

    Returns:
        list[object]: list として扱える値.
    """
    assert isinstance(value, list)
    return cast("list[object]", value)


def require_str_list(value: object) -> list[str]:
    """値が string だけから成る TOML list であることを返す.

    Args:
        value (object): TOML 解析結果から取得した値.

    Returns:
        list[str]: string list として扱える値.
    """
    values = require_list(value)
    assert all(isinstance(item, str) for item in values)
    return cast("list[str]", values)


def import_linter_contracts() -> list[object]:
    """設定済み pyproject の import-linter contract list を返す.

    Returns:
        list[object]: import-linter が定義する contract.
    """
    pyproject = load_pyproject()
    tool = require_table(pyproject["tool"])
    importlinter = require_table(tool["importlinter"])
    return require_list(importlinter["contracts"])


def test_job_boundary_contract_reads_server_owned_import_linter_configuration() -> None:
    """Job boundary contractがserver workspace import-linter設定を読むことを検証する.

    Returns:
        None: server productがarchitecture contractの唯一のownerであることを検証して完了する.
    """
    assert PYPROJECT_PATH == SERVER_WORKSPACE_ROOT / "pyproject.toml"


def test_jobs_layer_is_part_of_import_linter_contract() -> None:
    """前提: layered architecture contract が pyproject に定義される.

    操作: contract の layer 順序を取得する.
    結果: jobs layer を含む期待順序と一致する.

    Returns:
        None: jobs layer の architecture 契約を検証する.
    """
    contracts = import_linter_contracts()
    layered_contract = next(
        require_table(contract)
        for contract in contracts
        if require_table(contract).get("name") == "Layered architecture"
    )

    assert require_str_list(layered_contract["layers"]) == [
        "osu_server.transports",
        "osu_server.jobs",
        "osu_server.services",
        "osu_server.repositories",
        "osu_server.infrastructure",
        "osu_server.domain",
        "osu_server.shared",
    ]


def test_jobs_and_transports_are_mutually_forbidden() -> None:
    """前提: import-linter に forbidden contract が定義される.

    操作: contract から source と forbidden module の組を収集する.
    結果: jobs と transports の相互依存を禁止する組が存在する.

    Returns:
        None: job transport boundary 契約を検証する.
    """
    contracts = import_linter_contracts()
    forbidden_relations = {
        (source, forbidden)
        for value in contracts
        if (contract := require_table(value)).get("type") == "forbidden"
        for source in require_str_list(contract.get("source_modules", []))
        for forbidden in require_str_list(contract.get("forbidden_modules", []))
    }

    assert ("osu_server.jobs", "osu_server.transports") in forbidden_relations
    assert ("osu_server.jobs", "osu_server.composition") in forbidden_relations
    assert ("osu_server.jobs", "osu_server.repositories.sqlalchemy") in forbidden_relations
    assert ("osu_server.jobs", "osu_server.infrastructure.database") in forbidden_relations
    assert ("osu_server.transports", "osu_server.jobs") in forbidden_relations


def test_infrastructure_jobs_exports_registry_only() -> None:
    """前提: infrastructure jobs package が import できる.

    操作: package が公開する attribute を検査する.
    結果: registry だけを export し legacy persistence API は export しない.

    Returns:
        None: infrastructure job export 契約を検証する.
    """
    assert hasattr(infrastructure_jobs, "JobRegistry")
    assert hasattr(infrastructure_jobs, "jobs")
    assert not hasattr(infrastructure_jobs, "register_all_jobs")
    assert not hasattr(infrastructure_jobs, "persist_channel_message")
    assert not hasattr(infrastructure_jobs, "persist_private_message")


def test_top_level_jobs_exports_application_registration_only() -> None:
    """前提: top-level jobs package が import できる.

    操作: package が公開する attribute を検査する.
    結果: application registration だけを export し persistence API は export しない.

    Returns:
        None: application job export 契約を検証する.
    """
    assert hasattr(application_jobs, "register_all_jobs")
    assert not hasattr(application_jobs, "persist_channel_message")
    assert not hasattr(application_jobs, "persist_private_message")


def test_legacy_chat_persistence_job_modules_are_absent_or_inert() -> None:
    """前提: legacy chat persistence job path が残る可能性がある.

    操作: 存在する legacy source の registration と persistence token を検査する.
    結果: path は不在または runtime persistence を起動しない.

    Returns:
        None: legacy chat job の inert 契約を検証する.
    """
    legacy_paths = [
        PROJECT_ROOT / "src/osu_server/infrastructure/jobs/message_persistence.py",
        PROJECT_ROOT / "src/osu_server/composition/jobs/__init__.py",
        PROJECT_ROOT / "src/osu_server/composition/jobs/message_persistence.py",
    ]

    for path in legacy_paths:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert "@jobs.register" not in source
        assert "sqlalchemy" not in source
        assert "ChannelMessageModel" not in source
        assert "PrivateMessageModel" not in source
        assert "persist_channel_message" not in source
        assert "persist_private_message" not in source
