"""architecture boundary contract の回帰テストを提供する."""

from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).parents[4]
SERVER_WORKSPACE_ROOT = PROJECT_ROOT / "apps" / "athena_server"
PYPROJECT_PATH = SERVER_WORKSPACE_ROOT / "pyproject.toml"
SOURCE_ROOT = SERVER_WORKSPACE_ROOT / "src" / "osu_server"
TEST_ROOT = SERVER_WORKSPACE_ROOT / "tests"
DEPRECATED_IMPORT_BASELINE = TEST_ROOT / "fixtures" / "architecture" / "deprecated_imports.txt"

type TomlTable = dict[str, object]


@dataclass(frozen=True, slots=True)
class BoundaryRule:
    """source path に適用する import boundary 規則を表す.

    Attributes:
        name (str): failure message に表示する規則名.
        source_path (Path): 規則を走査する source root.
        forbidden_roots (tuple[str, ...]): import を禁止する module root.
    """

    name: str
    source_path: Path
    forbidden_roots: tuple[str, ...]


def test_architecture_contract_reads_server_owned_source_and_import_policy() -> None:
    """Architecture boundary verifierがcutover後の唯一のserver ownerを読むことを検証する.

    Rootがorchestration-only workspaceへ切り替わった後も、architecture source scanと
    import-linter contractが同じ`apps/athena_server` ownerを検証することを確認する.

    Returns:
        None: source rootとmanifest pathのownership一致を検証して完了する.
    """
    server_workspace_root = PROJECT_ROOT / "apps" / "athena_server"

    assert server_workspace_root / "src" / "osu_server" == SOURCE_ROOT
    assert server_workspace_root / "pyproject.toml" == PYPROJECT_PATH


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
        name="stable bancho login identity use-case boundary",
        source_path=SOURCE_ROOT / "transports" / "stable" / "bancho" / "workflows",
        forbidden_roots=("osu_server.services.commands.identity.auth_service",),
    ),
    BoundaryRule(
        name="stable bancho lifecycle identity query boundary",
        source_path=SOURCE_ROOT / "transports" / "stable" / "bancho" / "listeners",
        forbidden_roots=("osu_server.repositories.interfaces.session_store",),
    ),
    BoundaryRule(
        name="legacy web identity use-case boundary",
        source_path=SOURCE_ROOT / "transports" / "stable" / "web_legacy",
        forbidden_roots=(
            "osu_server.services.commands.identity.auth_service",
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

REMOVED_ARCHITECTURE_ENTRYPOINTS = (
    SOURCE_ROOT / "infrastructure" / "di",
    SOURCE_ROOT / "composition" / "service_registry.py",
    SOURCE_ROOT / "composition" / "worker_runtime.py",
    SOURCE_ROOT / "domain" / "bancho_bot.py",
    SOURCE_ROOT / "domain" / "legacy_getscores.py",
    SOURCE_ROOT / "domain" / "system_user.py",
    SOURCE_ROOT / "services" / "auth_service.py",
    SOURCE_ROOT / "services" / "bancho_bot",
    SOURCE_ROOT / "services" / "beatmap_mirror",
    SOURCE_ROOT / "services" / "blob_storage_service.py",
    SOURCE_ROOT / "services" / "channel_service.py",
    SOURCE_ROOT / "services" / "chat_service.py",
    SOURCE_ROOT / "services" / "online_users.py",
    SOURCE_ROOT / "services" / "password_service.py",
    SOURCE_ROOT / "services" / "permission_service.py",
    SOURCE_ROOT / "services" / "private_message_service.py",
    SOURCE_ROOT / "services" / "queries" / "chat" / "channel_service.py",
    SOURCE_ROOT / "services" / "queries" / "identity" / "online_users.py",
    SOURCE_ROOT / "services" / "queries" / "identity" / "online_users_service.py",
    SOURCE_ROOT / "services" / "score_authorization_service.py",
    SOURCE_ROOT / "services" / "session_authorization_service.py",
    SOURCE_ROOT / "transports" / "bancho",
    SOURCE_ROOT / "transports" / "signalr",
    SOURCE_ROOT / "transports" / "web_legacy",
)

BEATMAP_FETCH_JOB_ADAPTER_FILE = SOURCE_ROOT / "jobs" / "beatmap_fetch.py"
BEATMAP_FETCH_JOB_FORBIDDEN_IMPORT_ROOTS = (
    "osu_server.infrastructure.storage",
    "osu_server.repositories",
    "osu_server.services.queries.beatmaps.mirror",
    "osu_server.services.commands.storage.blob_storage",
    "osu_server.services.commands.beatmaps",
)

DEPRECATED_EXACT_ROOTS = (
    "osu_server.infrastructure.di",
    "osu_server.composition.service_registry",
    "osu_server.composition.worker_runtime",
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
    ("osu_server", "repositories", "interfaces"): (
        4,
        {"commands", "queries", "session_store", "unit_of_work"},
    ),
    ("osu_server", "repositories", "sqlalchemy"): (
        4,
        {"commands", "queries", "models", "unit_of_work"},
    ),
    ("osu_server", "repositories", "memory"): (
        4,
        {"commands", "queries", "session_store", "unit_of_work"},
    ),
}

REMOVED_DEPENDENCY_COMPOSITION_ROOTS = (
    "osu_server.infrastructure.di",
    "osu_server.composition.service_registry",
    "osu_server.composition.worker_runtime",
)


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


def import_linter_contracts() -> list[TomlTable]:
    """設定済み pyproject の import-linter contract を table として返す.

    Returns:
        list[TomlTable]: import-linter が定義する contract table.
    """
    pyproject = load_pyproject()
    tool = require_table(pyproject["tool"])
    importlinter = require_table(tool["importlinter"])
    return [require_table(contract) for contract in require_list(importlinter["contracts"])]


def imported_modules(path: Path) -> set[str]:
    """対象 file 内の absolute import module 名を収集する.

    Args:
        path (Path): 解析対象の Python file path.

    Returns:
        set[str]: import 文と from import 文から得た module 名.
    """
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
    """対象 file 内の name と attribute 名を収集する.

    Args:
        path (Path): 解析対象の Python file path.

    Returns:
        set[str]: AST に現れる識別子と attribute 名.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)

    return names


def module_matches_root(module: str, root: str) -> bool:
    """対象 module が root 自身または child module か判定する.

    Args:
        module (str): 判定対象の absolute module 名.
        root (str): 許容または禁止する module root.

    Returns:
        bool: root と一致するか root. で始まる場合は True.
    """
    return module == root or module.startswith(f"{root}.")


def deprecated_import_root(module: str) -> str | None:
    """対象 module から deprecated import root を導出する.

    Args:
        module (str): 判定対象の absolute module 名.

    Returns:
        str | None: deprecated root. 該当しない場合は None.
    """
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
    """現在の source tree の deprecated import を baseline 形式で返す.

    Returns:
        list[str]: relative path と deprecated root を tab で連結した entry.
    """
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
    """削除済み dependency composition root への import を収集する.

    Returns:
        list[str]: source と test に残る forbidden import entry.
    """
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


def path_has_python_sources(path: Path) -> bool:
    """対象 path が Python source または Python source を含む directory か判定する.

    Args:
        path (Path): 検査対象の file または directory path.

    Returns:
        bool: Python source が存在する場合は True.
    """
    if path.is_file():
        return path.suffix == ".py"
    if not path.is_dir():
        return False
    return any(
        child.suffix == ".py" and "__pycache__" not in child.parts for child in path.rglob("*.py")
    )


def expected_deprecated_imports() -> list[str]:
    """承認済み fixture から期待する deprecated import baseline を返す.

    Returns:
        list[str]: 空行と comment を除外した baseline entry.
    """
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
    """境界違反を読みやすい failure message に整形する.

    Args:
        rule (BoundaryRule): 適用した boundary 規則.
        path (Path): forbidden import を持つ source file.
        forbidden_root (str): 検出した禁止 module root.
        module (str): source file が import した module 名.

    Returns:
        str: relative path と import 関係を示す violation message.
    """
    relative_path = path.relative_to(PROJECT_ROOT).as_posix()
    return " ".join(
        (
            f"{rule.name}: {relative_path}",
            f"imports {forbidden_root} via {module}",
        )
    )


def test_import_linter_contracts_cover_new_architecture_boundaries() -> None:
    """前提: pyproject に新 architecture 用の import-linter contract が定義される.

    操作: contract 名と forbidden relation と independence module を収集する.
    結果: layer と adapter と domain の必須 boundary が全て含まれる.

    Returns:
        None: import-linter configuration 契約を検証する.
    """
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
    """前提: 将来の source path 用 boundary rule が定義される.

    操作: rule 名の集合を architecture map の期待集合と照合する.
    結果: 全 layer と transport family の rule が存在する.

    Returns:
        None: future boundary rule の網羅契約を検証する.
    """
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
    """前提: architecture source と path boundary rule が存在する.

    操作: 各 rule の source を走査し forbidden import を収集する.
    結果: architecture boundary に違反する import は存在しない.

    Returns:
        None: architecture import boundary 契約を検証する.
    """
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
    """前提: identity transport 用の use-case boundary rule が存在する.

    操作: 対象 transport source の forbidden import を収集する.
    結果: transport は legacy service や session store を直接 import しない.

    Returns:
        None: identity transport use-case boundary 契約を検証する.
    """
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
    """前提: service package path を transport family 名と分離する.

    操作: service source の relative path に禁止 fragment がないか調べる.
    結果: stable や lazer 等を含む service path は存在しない.

    Returns:
        None: service naming boundary 契約を検証する.
    """
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
    """前提: core domain と service は client-family wire concept から独立する.

    操作: import と AST name を wire root と wire name の禁止集合に照合する.
    結果: forbidden import と reference は共に存在しない.

    Returns:
        None: core client-family independence 契約を検証する.
    """
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
    """前提: regression test は新 transport family path を使う.

    操作: test source の import を deprecated transport root と照合する.
    結果: deprecated transport path を import する test は存在しない.

    Returns:
        None: transport test path 契約を検証する.
    """
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
    """前提: stable transport runtime source は family package へ移行済みである.

    操作: 必須 file と旧 root package の Python source を調べる.
    結果: 必須 file は存在し旧 root source と package は存在しない.

    Returns:
        None: stable transport placement 契約を検証する.
    """
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


def test_removed_architecture_entrypoints_have_no_python_sources() -> None:
    """前提: 削除対象の旧 architecture entrypoint が定義される.

    操作: 各 path に Python source が残るか調べる.
    結果: 削除済み entrypoint に Python source は存在しない.

    Returns:
        None: removed entrypoint の不在契約を検証する.
    """
    remaining = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in REMOVED_ARCHITECTURE_ENTRYPOINTS
        if path_has_python_sources(path)
    ]

    assert remaining == []


def test_beatmap_fetch_job_adapter_does_not_build_runtime_dependencies() -> None:
    """前提: beatmap fetch job adapter は DI から dependency を取得する.

    操作: adapter import を forbidden runtime dependency root と照合する.
    結果: adapter が storage や repository を直接構築する import は存在しない.

    Returns:
        None: beatmap fetch job boundary 契約を検証する.
    """
    violations = [
        f"{BEATMAP_FETCH_JOB_ADAPTER_FILE.relative_to(PROJECT_ROOT).as_posix()} imports {module}"
        for module in sorted(imported_modules(BEATMAP_FETCH_JOB_ADAPTER_FILE))
        for root in BEATMAP_FETCH_JOB_FORBIDDEN_IMPORT_ROOTS
        if module_matches_root(module, root)
    ]

    assert violations == []


def test_deprecated_architecture_imports_match_baseline() -> None:
    """前提: 承認済み deprecated import baseline fixture が存在する.

    操作: current source import を baseline 形式で収集して比較する.
    結果: deprecated import の集合は承認済み baseline と一致する.

    Returns:
        None: deprecated import migration 契約を検証する.
    """
    assert current_deprecated_imports() == expected_deprecated_imports()


def test_removed_dependency_composition_entrypoints_are_not_imported() -> None:
    """前提: 削除済み dependency composition root が定義される.

    操作: source と test の import を削除済み root と照合する.
    結果: 削除済み composition entrypoint を import する file は存在しない.

    Returns:
        None: removed composition import 契約を検証する.
    """
    assert current_removed_dependency_composition_imports() == []
