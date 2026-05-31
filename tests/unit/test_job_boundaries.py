"""Worker job boundary regression tests."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

import osu_server.infrastructure.jobs as infrastructure_jobs
import osu_server.jobs as application_jobs

PROJECT_ROOT = Path(__file__).parents[2]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"

type TomlTable = dict[str, object]


def load_pyproject() -> TomlTable:
    """Load pyproject.toml for boundary contract assertions."""
    return cast("TomlTable", tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8")))


def require_table(value: object) -> TomlTable:
    assert isinstance(value, dict)
    return cast("TomlTable", value)


def require_list(value: object) -> list[object]:
    assert isinstance(value, list)
    return cast("list[object]", value)


def require_str_list(value: object) -> list[str]:
    values = require_list(value)
    assert all(isinstance(item, str) for item in values)
    return cast("list[str]", values)


def import_linter_contracts() -> list[object]:
    pyproject = load_pyproject()
    tool = require_table(pyproject["tool"])
    importlinter = require_table(tool["importlinter"])
    return require_list(importlinter["contracts"])


def test_jobs_layer_is_part_of_import_linter_contract() -> None:
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
        "osu_server.domain",
        "osu_server.infrastructure",
        "osu_server.shared",
    ]


def test_jobs_and_transports_are_mutually_forbidden() -> None:
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
    assert hasattr(infrastructure_jobs, "JobRegistry")
    assert hasattr(infrastructure_jobs, "jobs")
    assert not hasattr(infrastructure_jobs, "register_all_jobs")
    assert not hasattr(infrastructure_jobs, "persist_channel_message")
    assert not hasattr(infrastructure_jobs, "persist_private_message")


def test_top_level_jobs_exports_application_registration_only() -> None:
    assert hasattr(application_jobs, "register_all_jobs")
    assert not hasattr(application_jobs, "persist_channel_message")
    assert not hasattr(application_jobs, "persist_private_message")
