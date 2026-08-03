"""アーキテクチャ package skeleton の回帰契約を検証する."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).parents[4]
SOURCE_ROOT = PROJECT_ROOT / "apps" / "athena_server" / "src" / "osu_server"


def test_package_skeleton_audits_read_server_owned_sources() -> None:
    """Package skeleton auditがserver workspaceのphysical sourceを読むことを検証する.

    Namespace構造とinert packageのAST検査は、rootの削除済みsource treeではなくserver productの
    source rootに対して実行されることを確認する.

    Returns:
        None: package skeleton source rootのownershipを検証して完了する.
    """
    assert SOURCE_ROOT == PROJECT_ROOT / "apps" / "athena_server" / "src" / "osu_server"


PACKAGE_ROOTS = (
    # Composition providers are established before the rest of the refactor.
    "osu_server.composition.providers",
    # Command/query use-case boundaries.
    "osu_server.services.commands",
    "osu_server.services.commands.identity",
    "osu_server.services.commands.chat",
    "osu_server.services.commands.beatmaps",
    "osu_server.services.commands.scores",
    "osu_server.services.commands.storage",
    "osu_server.services.queries",
    "osu_server.services.queries.identity",
    "osu_server.services.queries.chat",
    "osu_server.services.queries.beatmaps",
    "osu_server.services.queries.scores",
    # Command/query repository boundaries.
    "osu_server.repositories.interfaces.commands",
    "osu_server.repositories.interfaces.queries",
    "osu_server.repositories.sqlalchemy.commands",
    "osu_server.repositories.sqlalchemy.queries",
    "osu_server.repositories.memory.commands",
    "osu_server.repositories.memory.queries",
    # Bounded domain and compatibility context roots.
    "osu_server.domain.identity",
    "osu_server.domain.chat",
    "osu_server.domain.beatmaps",
    "osu_server.domain.scores",
    "osu_server.domain.storage",
    "osu_server.domain.compatibility",
    "osu_server.domain.compatibility.stable",
    "osu_server.domain.events",
    # Transport family and mapper roots.
    "osu_server.transports.stable",
    "osu_server.transports.stable.bancho",
    "osu_server.transports.stable.bancho.protocol",
    "osu_server.transports.stable.bancho.handlers",
    "osu_server.transports.stable.bancho.workflows",
    "osu_server.transports.stable.bancho.mappers",
    "osu_server.transports.stable.web_legacy",
    "osu_server.transports.stable.web_legacy.endpoints",
    "osu_server.transports.stable.web_legacy.mappers",
    "osu_server.transports.lazer",
    "osu_server.transports.lazer.api",
    "osu_server.transports.lazer.api.mappers",
    "osu_server.transports.lazer.signalr",
    "osu_server.transports.lazer.signalr.mappers",
    "osu_server.transports.api.public",
    "osu_server.transports.api.public.mappers",
    "osu_server.transports.api.admin",
    "osu_server.transports.api.admin.mappers",
)

SKELETON_INIT_MODULES = tuple(
    module
    for module in PACKAGE_ROOTS
    if module
    not in {
        "osu_server.composition.providers",
        "osu_server.domain.chat",
    }
)

LEGACY_FACADE_ROOTS = (
    "osu_server.composition.service_registry",
    "osu_server.composition.worker_runtime",
    "osu_server.infrastructure.di",
    "osu_server.services.auth_service",
    "osu_server.services.permission_service",
    "osu_server.services.session_authorization_service",
    "osu_server.services.chat_service",
    "osu_server.services.bancho_bot",
    "osu_server.services.beatmap_mirror",
    "osu_server.services.score_submission_service",
    "osu_server.domain.system_user",
    "osu_server.domain.bancho_bot",
    "osu_server.domain.legacy_getscores",
    "osu_server.repositories.interfaces.chat_repository",
    "osu_server.repositories.memory.chat_repository",
    "osu_server.repositories.sqlalchemy.chat_repository",
    "osu_server.services.queries.chat.channel_service",
    "osu_server.transports.bancho",
    "osu_server.transports.web_legacy",
    "osu_server.transports.signalr",
)

INERT_TRANSPORT_ROOTS = (
    "osu_server.transports.lazer",
    "osu_server.transports.lazer.api",
    "osu_server.transports.lazer.api.mappers",
    "osu_server.transports.lazer.signalr",
    "osu_server.transports.lazer.signalr.mappers",
    "osu_server.transports.api",
    "osu_server.transports.api.public",
    "osu_server.transports.api.public.mappers",
    "osu_server.transports.api.admin",
    "osu_server.transports.api.admin.mappers",
)


def test_new_architecture_package_roots_import_as_packages() -> None:
    """前提: 新しい architecture package root が定義されている.

    操作: 各 root を import して package metadata を検査する.
    結果: 全 root が submodule を持つ package として import できる.

    Returns:
        None: package root の import 契約を検証する.
    """
    for module_name in PACKAGE_ROOTS:
        module = importlib.import_module(module_name)

        assert isinstance(module, ModuleType)
        assert module.__spec__ is not None
        assert module.__spec__.submodule_search_locations is not None, module_name


def test_domain_chat_flat_module_is_not_kept_next_to_package() -> None:
    """前提: chat domain は package へ移行済みである.

    操作: 旧 flat module の path を調べる.
    結果: package と競合する chat.py は存在しない.

    Returns:
        None: domain package 移行契約を検証する.
    """
    assert not (SOURCE_ROOT / "domain" / "chat.py").exists()


def test_new_package_roots_do_not_reexport_deprecated_paths() -> None:
    """前提: 新 package root の __init__.py が存在する.

    操作: 各 __init__.py の absolute import を legacy facade と照合する.
    結果: deprecated path を再 export する import は存在しない.

    Returns:
        None: package boundary の import 契約を検証する.
    """
    facade_imports = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} imports {module}"
        for module_name in SKELETON_INIT_MODULES
        for path in [_module_init_path(module_name)]
        for module in _absolute_imports(path)
        if _is_legacy_facade_import(module)
    ]

    assert facade_imports == []


def test_future_transport_family_roots_are_inert() -> None:
    """前提: 将来利用する transport family root が skeleton である.

    操作: 各 __init__.py を AST 解析し docstring 以外の node を収集する.
    結果: runtime behavior を持つ node は存在しない.

    Returns:
        None: transport skeleton の inert 契約を検証する.
    """
    behavior_nodes = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} contains {type(node).__name__}"
        for module_name in INERT_TRANSPORT_ROOTS
        for path in [_module_init_path(module_name)]
        for node in _non_docstring_module_nodes(path)
    ]

    assert behavior_nodes == []


def _module_init_path(module_name: str) -> Path:
    """指定 module の __init__.py path を返す.

    Args:
        module_name (str): osu_server から始まる package module 名.

    Returns:
        Path: source root 配下の __init__.py path.
    """
    relative = Path(*module_name.split(".")[1:]) / "__init__.py"
    return SOURCE_ROOT / relative


def _non_docstring_module_nodes(path: Path) -> list[ast.stmt]:
    """対象 module 本文から先頭 docstring を除いた AST node を返す.

    Args:
        path (Path): 解析対象の Python module path.

    Returns:
        list[ast.stmt]: docstring 以外の module body node.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    body = list(tree.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _absolute_imports(path: Path) -> set[str]:
    """対象 module 内の absolute import module 名を収集する.

    Args:
        path (Path): 解析対象の Python module path.

    Returns:
        set[str]: __future__ を除く absolute import module 名.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)

    modules.discard("__future__")
    return modules


def _is_legacy_facade_import(module: str) -> bool:
    """対象 module が legacy facade root を指すか判定する.

    Args:
        module (str): 判定対象の absolute module 名.

    Returns:
        bool: legacy facade root またはその child なら True.
    """
    return any(module == root or module.startswith(f"{root}.") for root in LEGACY_FACADE_ROOTS)
