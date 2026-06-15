"""Architecture boundary contract regression tests."""

from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).parents[2]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
SOURCE_ROOT = PROJECT_ROOT / "src" / "osu_server"
TEST_ROOT = PROJECT_ROOT / "tests"
DEPRECATED_IMPORT_BASELINE = (
    PROJECT_ROOT / "tests" / "fixtures" / "architecture" / "deprecated_imports.txt"
)

type TomlTable = dict[str, object]


@dataclass(frozen=True, slots=True)
class BoundaryRule:
    name: str
    source_path: Path
    forbidden_roots: tuple[str, ...]


FUTURE_BOUNDARY_RULES = (
    BoundaryRule(
        name="command services",
        source_path=SOURCE_ROOT / "services" / "commands",
        forbidden_roots=(
            "osu_server.transports",
            "osu_server.jobs",
            "osu_server.repositories.sqlalchemy",
            "osu_server.repositories.memory",
            "osu_server.infrastructure.database",
            "sqlalchemy",
            "taskiq",
            "starlette",
            "fastapi",
            "pydantic",
        ),
    ),
    BoundaryRule(
        name="query services",
        source_path=SOURCE_ROOT / "services" / "queries",
        forbidden_roots=(
            "osu_server.transports",
            "osu_server.jobs",
            "osu_server.repositories.interfaces.commands",
            "osu_server.repositories.interfaces.unit_of_work",
            "osu_server.repositories.sqlalchemy",
            "osu_server.repositories.memory",
            "osu_server.infrastructure.database",
            "sqlalchemy",
            "taskiq",
            "starlette",
            "fastapi",
            "pydantic",
        ),
    ),
    BoundaryRule(
        name="command repository interfaces",
        source_path=SOURCE_ROOT / "repositories" / "interfaces" / "commands",
        forbidden_roots=(
            "osu_server.repositories.sqlalchemy",
            "osu_server.repositories.memory",
            "osu_server.infrastructure",
            "osu_server.services",
            "osu_server.transports",
            "osu_server.jobs",
            "sqlalchemy",
            "taskiq",
            "starlette",
            "fastapi",
            "pydantic",
            "httpx",
        ),
    ),
    BoundaryRule(
        name="query repository interfaces",
        source_path=SOURCE_ROOT / "repositories" / "interfaces" / "queries",
        forbidden_roots=(
            "osu_server.repositories.interfaces.commands",
            "osu_server.repositories.interfaces.unit_of_work",
            "osu_server.repositories.sqlalchemy",
            "osu_server.repositories.memory",
            "osu_server.infrastructure",
            "osu_server.services",
            "osu_server.transports",
            "osu_server.jobs",
            "sqlalchemy",
            "taskiq",
            "starlette",
            "fastapi",
            "pydantic",
            "httpx",
        ),
    ),
    BoundaryRule(
        name="stable transport family",
        source_path=SOURCE_ROOT / "transports" / "stable",
        forbidden_roots=(
            "osu_server.transports.lazer",
            "osu_server.transports.api",
            "osu_server.repositories.sqlalchemy",
            "osu_server.repositories.memory",
            "osu_server.infrastructure.database",
            "sqlalchemy",
        ),
    ),
    BoundaryRule(
        name="lazer transport family",
        source_path=SOURCE_ROOT / "transports" / "lazer",
        forbidden_roots=(
            "osu_server.transports.stable",
            "osu_server.transports.api",
            "osu_server.repositories.sqlalchemy",
            "osu_server.repositories.memory",
            "osu_server.infrastructure.database",
            "sqlalchemy",
        ),
    ),
    BoundaryRule(
        name="first-party API transport family",
        source_path=SOURCE_ROOT / "transports" / "api",
        forbidden_roots=(
            "osu_server.transports.stable",
            "osu_server.transports.lazer",
            "osu_server.transports.bancho",
            "osu_server.transports.web_legacy",
            "osu_server.transports.signalr",
            "osu_server.repositories.sqlalchemy",
            "osu_server.repositories.memory",
            "osu_server.infrastructure.database",
            "sqlalchemy",
        ),
    ),
    BoundaryRule(
        name="job adapters",
        source_path=SOURCE_ROOT / "jobs",
        forbidden_roots=(
            "osu_server.transports",
            "osu_server.repositories.sqlalchemy",
            "osu_server.repositories.memory",
            "osu_server.infrastructure.database",
            "sqlalchemy",
            "starlette",
            "fastapi",
        ),
    ),
    BoundaryRule(
        name="domain",
        source_path=SOURCE_ROOT / "domain",
        forbidden_roots=(
            "osu_server.repositories",
            "osu_server.infrastructure",
            "osu_server.services",
            "osu_server.transports",
            "osu_server.jobs",
            "sqlalchemy",
            "taskiq",
            "starlette",
            "fastapi",
            "pydantic",
            "httpx",
            "aiohttp",
            "requests",
            "valkey",
        ),
    ),
)

IDENTITY_TRANSPORT_USE_CASE_RULES = (
    BoundaryRule(
        name="bancho login identity use-case boundary",
        source_path=SOURCE_ROOT / "transports" / "bancho" / "workflows",
        forbidden_roots=("osu_server.services.auth_service",),
    ),
    BoundaryRule(
        name="bancho lifecycle identity query boundary",
        source_path=SOURCE_ROOT / "transports" / "bancho" / "listeners",
        forbidden_roots=("osu_server.services.online_users",),
    ),
    BoundaryRule(
        name="legacy web identity use-case boundary",
        source_path=SOURCE_ROOT / "transports" / "web_legacy",
        forbidden_roots=(
            "osu_server.services.auth_service",
            "osu_server.services.legacy_web_auth_service",
        ),
    ),
)

SERVICE_TRANSPORT_NAMED_PATH_FRAGMENTS = (
    "legacy_getscores",
    "legacy_web_auth",
    "web_legacy",
    "lazer",
    "signalr",
)

CORE_DOMAIN_AND_SERVICE_ROOTS = (
    SOURCE_ROOT / "domain" / "beatmaps",
    SOURCE_ROOT / "domain" / "chat",
    SOURCE_ROOT / "domain" / "events",
    SOURCE_ROOT / "domain" / "identity",
    SOURCE_ROOT / "domain" / "scores",
    SOURCE_ROOT / "domain" / "storage",
    SOURCE_ROOT / "services",
)

CLIENT_FAMILY_WIRE_IMPORT_ROOTS = (
    "osu_server.transports.stable.bancho.protocol",
    "osu_server.transports.stable.bancho.parsers",
    "osu_server.transports.stable.bancho.mappers",
    "osu_server.transports.stable.web_legacy.mappers",
    "osu_server.transports.lazer.api.mappers",
    "osu_server.transports.lazer.signalr.mappers",
    "osu_server.transports.api.public.mappers",
    "osu_server.transports.api.admin.mappers",
)

CLIENT_FAMILY_WIRE_NAMES = frozenset(
    {
        "BanchoClientPermission",
        "BanchoString",
        "ClientPacketID",
        "GetscoresQueryParser",
        "GetscoresStatusMapper",
        "PacketHeader",
        "ServerPacketID",
        "StableBanchoAuthorizationOutput",
        "StableScorePayloadParser",
        "StableScoreSubmitMapper",
        "map_stable_bancho_authorization",
        "mod_combination_to_stable_bitmask",
        "parse_client_info",
        "parse_login_body",
        "read_packets",
        "stable_mod_bitmask_to_mod_combination",
        "write_packet",
    }
)

DEPRECATED_TRANSPORT_IMPORT_ROOTS = (
    "osu_server.transports.bancho",
    "osu_server.transports.signalr",
    "osu_server.transports.web_legacy",
)

STABLE_TRANSPORT_RUNTIME_FILES = (
    SOURCE_ROOT / "transports" / "stable" / "bancho" / "endpoint.py",
    SOURCE_ROOT / "transports" / "stable" / "bancho" / "dispatch.py",
    SOURCE_ROOT / "transports" / "stable" / "bancho" / "protocol" / "reader.py",
    SOURCE_ROOT / "transports" / "stable" / "web_legacy" / "getscores.py",
    SOURCE_ROOT / "transports" / "stable" / "web_legacy" / "registration.py",
    SOURCE_ROOT / "transports" / "stable" / "web_legacy" / "score_submit.py",
)

BEATMAP_FETCH_JOB_ADAPTER_FILE = SOURCE_ROOT / "jobs" / "beatmap_fetch.py"
BEATMAP_FETCH_JOB_FORBIDDEN_IMPORT_ROOTS = (
    "osu_server.infrastructure.storage",
    "osu_server.repositories",
    "osu_server.services.beatmap_mirror",
    "osu_server.services.blob_storage_service",
    "osu_server.services.commands.beatmaps",
)

DEPRECATED_EXACT_ROOTS = (
    "osu_server.infrastructure.di",
    "osu_server.composition.service_registry",
    "osu_server.composition.worker_runtime",
    "osu_server.transports.api",
    "osu_server.transports.bancho",
    "osu_server.transports.signalr",
    "osu_server.transports.web_legacy",
)

DEPRECATED_PACKAGE_REPLACEMENTS = {
    ("osu_server", "services"): (3, {"commands", "queries"}),
    (
        "osu_server",
        "domain",
    ): (3, {"beatmaps", "chat", "compatibility", "events", "identity", "scores", "storage"}),
    ("osu_server", "repositories", "interfaces"): (4, {"commands", "queries"}),
    ("osu_server", "repositories", "sqlalchemy"): (4, {"commands", "queries", "models"}),
    ("osu_server", "repositories", "memory"): (4, {"commands", "queries"}),
}

REMOVED_DEPENDENCY_COMPOSITION_ROOTS = (
    "osu_server.infrastructure.di",
    "osu_server.composition.service_registry",
    "osu_server.composition.worker_runtime",
)


def load_pyproject() -> TomlTable:
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


def import_linter_contracts() -> list[TomlTable]:
    pyproject = load_pyproject()
    tool = require_table(pyproject["tool"])
    importlinter = require_table(tool["importlinter"])
    return [require_table(contract) for contract in require_list(importlinter["contracts"])]


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
            modules.update(
                f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*"
            )

    return modules


def referenced_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)

    return names


def module_matches_root(module: str, root: str) -> bool:
    return module == root or module.startswith(f"{root}.")


def deprecated_import_root(module: str) -> str | None:
    for root in DEPRECATED_EXACT_ROOTS:
        if module_matches_root(module, root):
            return root

    parts = module.split(".")
    for prefix, (root_length, allowed_replacements) in DEPRECATED_PACKAGE_REPLACEMENTS.items():
        if (
            tuple(parts[: len(prefix)]) == prefix
            and len(parts) >= root_length
            and parts[root_length - 1] not in allowed_replacements
        ):
            return ".".join(parts[:root_length])

    return None


def current_deprecated_imports() -> list[str]:
    entries: set[str] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        for module in imported_modules(path):
            root = deprecated_import_root(module)
            if root is not None:
                entries.add(f"{relative_path}\t{root}")

    return sorted(entries)


def current_removed_dependency_composition_imports() -> list[str]:
    entries: set[str] = set()
    for root in (SOURCE_ROOT, TEST_ROOT):
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            relative_path = path.relative_to(PROJECT_ROOT).as_posix()
            for module in imported_modules(path):
                for removed_root in REMOVED_DEPENDENCY_COMPOSITION_ROOTS:
                    if module_matches_root(module, removed_root):
                        entries.add(f"{relative_path}\t{removed_root}")

    return sorted(entries)


def expected_deprecated_imports() -> list[str]:
    return [
        line
        for line in DEPRECATED_IMPORT_BASELINE.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]


def format_boundary_violation(
    *,
    rule: BoundaryRule,
    path: Path,
    forbidden_root: str,
    module: str,
) -> str:
    relative_path = path.relative_to(PROJECT_ROOT).as_posix()
    return " ".join(
        (
            f"{rule.name}: {relative_path}",
            f"imports {forbidden_root} via {module}",
        )
    )


def test_import_linter_contracts_cover_new_architecture_boundaries() -> None:
    contracts = import_linter_contracts()
    contract_names = {str(contract["name"]) for contract in contracts}
    forbidden_relations = {
        (source, forbidden)
        for contract in contracts
        if contract.get("type") == "forbidden"
        for source in require_str_list(contract.get("source_modules", []))
        for forbidden in require_str_list(contract.get("forbidden_modules", []))
    }
    independence_modules = {
        module
        for contract in contracts
        if contract.get("type") == "independence"
        for module in require_str_list(contract.get("modules", []))
    }

    assert {
        "Layered architecture",
        "Services stay adapter independent",
        "Transports stay persistence-adapter independent",
        "Jobs stay persistence-adapter independent",
        "Repository interfaces stay pure",
        "Transport family packages stay independent",
        "Domain has no I/O dependencies",
    } <= contract_names

    assert {
        ("osu_server.services", "osu_server.repositories.sqlalchemy"),
        ("osu_server.services", "osu_server.repositories.memory"),
        ("osu_server.services", "osu_server.infrastructure.database"),
        ("osu_server.services", "sqlalchemy"),
        ("osu_server.transports", "osu_server.repositories.sqlalchemy"),
        ("osu_server.transports", "osu_server.repositories.memory"),
        ("osu_server.transports", "osu_server.infrastructure.database"),
        ("osu_server.jobs", "osu_server.repositories.sqlalchemy"),
        ("osu_server.jobs", "osu_server.repositories.memory"),
        ("osu_server.jobs", "osu_server.infrastructure.database"),
        ("osu_server.repositories.interfaces", "osu_server.repositories.sqlalchemy"),
        ("osu_server.repositories.interfaces", "osu_server.repositories.memory"),
        ("osu_server.repositories.interfaces", "osu_server.infrastructure"),
        ("osu_server.repositories.interfaces", "sqlalchemy"),
        ("osu_server.domain", "osu_server.services"),
        ("osu_server.domain", "osu_server.jobs"),
        ("osu_server.domain", "pydantic"),
        ("osu_server.domain", "starlette"),
        ("osu_server.domain", "fastapi"),
        ("osu_server.domain", "taskiq"),
    } <= forbidden_relations

    assert {
        "osu_server.transports.stable",
        "osu_server.transports.lazer",
        "osu_server.transports.api",
    } <= independence_modules


def test_future_path_boundary_rules_cover_architecture_map() -> None:
    assert {rule.name for rule in FUTURE_BOUNDARY_RULES} == {
        "command services",
        "query services",
        "command repository interfaces",
        "query repository interfaces",
        "stable transport family",
        "lazer transport family",
        "first-party API transport family",
        "job adapters",
        "domain",
    }


def test_architecture_boundary_rules_have_no_forbidden_imports() -> None:
    violations = [
        format_boundary_violation(
            rule=rule,
            path=path,
            forbidden_root=forbidden_root,
            module=module,
        )
        for rule in FUTURE_BOUNDARY_RULES
        if rule.source_path.exists()
        for path in sorted(rule.source_path.rglob("*.py"))
        if "__pycache__" not in path.parts
        for module in sorted(imported_modules(path))
        for forbidden_root in rule.forbidden_roots
        if module_matches_root(module, forbidden_root)
    ]

    assert violations == []


def test_identity_transports_use_command_or_query_use_case_boundaries() -> None:
    violations = [
        format_boundary_violation(
            rule=rule,
            path=path,
            forbidden_root=forbidden_root,
            module=module,
        )
        for rule in IDENTITY_TRANSPORT_USE_CASE_RULES
        if rule.source_path.exists()
        for path in sorted(rule.source_path.rglob("*.py"))
        if "__pycache__" not in path.parts
        for module in sorted(imported_modules(path))
        for forbidden_root in rule.forbidden_roots
        if module_matches_root(module, forbidden_root)
    ]

    assert violations == []


def test_service_paths_do_not_encode_transport_family_names() -> None:
    service_paths = [
        path.relative_to(SOURCE_ROOT / "services").as_posix()
        for path in sorted((SOURCE_ROOT / "services").rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    violations = [
        path
        for path in service_paths
        for fragment in SERVICE_TRANSPORT_NAMED_PATH_FRAGMENTS
        if fragment in path
    ]

    assert violations == []


def test_core_domain_and_services_do_not_reference_client_family_wire_concepts() -> None:
    import_violations = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} imports {module}"
        for root in CORE_DOMAIN_AND_SERVICE_ROOTS
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
        for module in imported_modules(path)
        for forbidden_root in CLIENT_FAMILY_WIRE_IMPORT_ROOTS
        if module_matches_root(module, forbidden_root)
    ]
    name_violations = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} references {name}"
        for root in CORE_DOMAIN_AND_SERVICE_ROOTS
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
        for name in sorted(referenced_names(path) & CLIENT_FAMILY_WIRE_NAMES)
    ]

    assert import_violations == []
    assert name_violations == []


def test_transport_regression_tests_use_transport_family_paths() -> None:
    violations = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} imports {module}"
        for path in sorted(TEST_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
        for module in imported_modules(path)
        for root in DEPRECATED_TRANSPORT_IMPORT_ROOTS
        if module_matches_root(module, root)
    ]

    assert violations == []


def test_stable_transport_runtime_sources_live_in_stable_family() -> None:
    missing_runtime_files = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in STABLE_TRANSPORT_RUNTIME_FILES
        if not path.exists()
    ]
    old_root_sources = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for package in ("bancho", "web_legacy")
        for path in sorted((SOURCE_ROOT / "transports" / package).rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    old_root_packages = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for package in ("bancho", "web_legacy")
        for path in [SOURCE_ROOT / "transports" / package]
        if path.exists()
    ]

    assert missing_runtime_files == []
    assert old_root_sources == []
    assert old_root_packages == []


def test_beatmap_fetch_job_adapter_does_not_build_runtime_dependencies() -> None:
    violations = [
        f"{BEATMAP_FETCH_JOB_ADAPTER_FILE.relative_to(PROJECT_ROOT).as_posix()} imports {module}"
        for module in sorted(imported_modules(BEATMAP_FETCH_JOB_ADAPTER_FILE))
        for root in BEATMAP_FETCH_JOB_FORBIDDEN_IMPORT_ROOTS
        if module_matches_root(module, root)
    ]

    assert violations == []


def test_deprecated_architecture_imports_match_baseline() -> None:
    assert current_deprecated_imports() == expected_deprecated_imports()


def test_removed_dependency_composition_entrypoints_are_not_imported() -> None:
    assert current_removed_dependency_composition_imports() == []
