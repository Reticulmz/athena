"""Architecture package skeleton regression tests."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src" / "osu_server"

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
    "osu_server.services.commands.identity.auth_service",
    "osu_server.services.chat_service",
    "osu_server.services.score_submission_service",
    "osu_server.repositories.interfaces.chat_repository",
    "osu_server.repositories.memory.chat_repository",
    "osu_server.repositories.sqlalchemy.chat_repository",
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
    for module_name in PACKAGE_ROOTS:
        module = importlib.import_module(module_name)

        assert isinstance(module, ModuleType)
        assert module.__spec__ is not None
        assert module.__spec__.submodule_search_locations is not None, module_name


def test_domain_chat_flat_module_is_not_kept_next_to_package() -> None:
    assert not (SOURCE_ROOT / "domain" / "chat.py").exists()


def test_new_package_roots_do_not_reexport_deprecated_paths() -> None:
    facade_imports = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} imports {module}"
        for module_name in SKELETON_INIT_MODULES
        for path in [_module_init_path(module_name)]
        for module in _absolute_imports(path)
        if _is_legacy_facade_import(module)
    ]

    assert facade_imports == []


def test_future_transport_family_roots_are_inert() -> None:
    behavior_nodes = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} contains {type(node).__name__}"
        for module_name in INERT_TRANSPORT_ROOTS
        for path in [_module_init_path(module_name)]
        for node in _non_docstring_module_nodes(path)
    ]

    assert behavior_nodes == []


def _module_init_path(module_name: str) -> Path:
    relative = Path(*module_name.split(".")[1:]) / "__init__.py"
    return SOURCE_ROOT / relative


def _non_docstring_module_nodes(path: Path) -> list[ast.stmt]:
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
    return any(module == root or module.startswith(f"{root}.") for root in LEGACY_FACADE_ROOTS)
