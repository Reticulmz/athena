"""Persistence boundary contract tests for command/query repositories."""

from __future__ import annotations

import ast
import inspect
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import get_type_hints

from osu_server.repositories.interfaces.commands import (
    BeatmapCommandRepository,
    BlobCommandRepository,
    ChannelCommandRepository,
    ChatCommandRepository,
    ReplayCommandRepository,
    RoleCommandRepository,
    ScoreCommandRepository,
    ScoreSubmissionCommandRepository,
    UserCommandRepository,
)
from osu_server.repositories.interfaces.queries import (
    BeatmapQueryRepository,
    BeatmapScoreListingQueryRepository,
    BlobQueryRepository,
    ChannelQueryRepository,
    ChatHistoryQueryRepository,
    RoleQueryRepository,
    ScoreQueryRepository,
    UserQueryRepository,
)
from osu_server.repositories.interfaces.unit_of_work import UnitOfWork, UnitOfWorkFactory

PROJECT_ROOT = Path(__file__).parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src" / "osu_server"
COMMAND_INTERFACE_ROOT = SOURCE_ROOT / "repositories" / "interfaces" / "commands"
QUERY_INTERFACE_ROOT = SOURCE_ROOT / "repositories" / "interfaces" / "queries"
SERVICE_FACING_SOURCE_ROOTS = (
    SOURCE_ROOT / "services",
    SOURCE_ROOT / "transports",
    SOURCE_ROOT / "jobs",
)
SERVICE_FACING_TEST_ROOTS = (
    PROJECT_ROOT / "tests" / "unit" / "services",
    PROJECT_ROOT / "tests" / "unit" / "transports",
    PROJECT_ROOT / "tests" / "unit" / "jobs",
    PROJECT_ROOT / "tests" / "unit" / "test_worker.py",
)

COMMAND_REPOSITORY_ATTRIBUTES = {
    "users": UserCommandRepository,
    "roles": RoleCommandRepository,
    "channels": ChannelCommandRepository,
    "chat": ChatCommandRepository,
    "scores": ScoreCommandRepository,
    "submissions": ScoreSubmissionCommandRepository,
    "replays": ReplayCommandRepository,
    "blobs": BlobCommandRepository,
    "beatmaps": BeatmapCommandRepository,
}
COMMAND_REPOSITORY_GLOBALS = {
    repository.__name__: repository for repository in COMMAND_REPOSITORY_ATTRIBUTES.values()
}

QUERY_REPOSITORIES = (
    UserQueryRepository,
    RoleQueryRepository,
    ChannelQueryRepository,
    ScoreQueryRepository,
    BeatmapQueryRepository,
    BlobQueryRepository,
    ChatHistoryQueryRepository,
    BeatmapScoreListingQueryRepository,
)

FORBIDDEN_INTERFACE_IMPORT_ROOTS = (
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
)
FORBIDDEN_SERVICE_FACING_PERSISTENCE_ROOTS = (
    "osu_server.repositories.sqlalchemy.models",
    "osu_server.repositories.sqlalchemy.beatmap_repository",
    "osu_server.repositories.sqlalchemy.blob_repository",
    "osu_server.repositories.sqlalchemy.channel_repository",
    "osu_server.repositories.sqlalchemy.chat_repository",
    "osu_server.repositories.sqlalchemy.replay_repository",
    "osu_server.repositories.sqlalchemy.role_repository",
    "osu_server.repositories.sqlalchemy.score_repository",
    "osu_server.repositories.sqlalchemy.submission_repository",
    "osu_server.repositories.sqlalchemy.user_repository",
    "osu_server.infrastructure.database",
    "sqlalchemy",
)

MUTATION_METHOD_PREFIXES = (
    "add",
    "assign",
    "attach",
    "create",
    "delete",
    "mark",
    "save",
    "set",
    "sync",
    "try_mark",
    "update",
)


def test_unit_of_work_exposes_command_repositories_only() -> None:
    hints = get_type_hints(
        UnitOfWork,
        globalns=COMMAND_REPOSITORY_GLOBALS,
        include_extras=True,
    )

    assert hints == COMMAND_REPOSITORY_ATTRIBUTES
    assert inspect.iscoroutinefunction(UnitOfWork.commit)
    assert inspect.iscoroutinefunction(UnitOfWork.rollback)


def test_unit_of_work_factory_opens_async_context_manager() -> None:
    hints = get_type_hints(
        UnitOfWorkFactory.__call__,
        globalns={
            "AbstractAsyncContextManager": AbstractAsyncContextManager,
            "UnitOfWork": UnitOfWork,
        },
        include_extras=True,
    )

    assert hints["return"] == AbstractAsyncContextManager[UnitOfWork]


def test_command_repository_contracts_include_mutations_and_consistency_checks() -> None:
    assert set(COMMAND_REPOSITORY_ATTRIBUTES.values()) == {
        UserCommandRepository,
        RoleCommandRepository,
        ChannelCommandRepository,
        ChatCommandRepository,
        ScoreCommandRepository,
        ScoreSubmissionCommandRepository,
        ReplayCommandRepository,
        BlobCommandRepository,
        BeatmapCommandRepository,
    }
    assert _public_async_methods(ScoreCommandRepository) == {
        "create",
        "exists_by_online_checksum",
        "get_by_id",
        "get_by_online_checksum",
    }
    assert _public_async_methods(BeatmapCommandRepository) >= {
        "save_beatmapset_snapshot",
        "set_local_status_override",
        "try_mark_fetch_pending",
        "mark_fetch_succeeded",
        "mark_fetch_failed",
    }


def test_query_repository_contracts_are_read_only() -> None:
    for repository in QUERY_REPOSITORIES:
        mutation_methods = [
            name
            for name in _public_async_methods(repository)
            if name.startswith(MUTATION_METHOD_PREFIXES)
        ]

        assert mutation_methods == [], repository.__name__

    assert _public_async_methods(BeatmapScoreListingQueryRepository) == {
        "find_by_checksum",
        "find_by_filename_in_beatmapset",
        "get_beatmapset",
    }


def test_persistence_boundary_interfaces_do_not_depend_on_adapters_or_runtime() -> None:
    violations = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} imports {forbidden_root} via {module}"
        for root in (COMMAND_INTERFACE_ROOT, QUERY_INTERFACE_ROOT)
        for path in sorted(root.rglob("*.py"))
        for module in _absolute_imports(path)
        for forbidden_root in FORBIDDEN_INTERFACE_IMPORT_ROOTS
        if _module_matches_root(module, forbidden_root)
    ]

    assert violations == []


def test_query_repository_interfaces_do_not_depend_on_command_boundaries() -> None:
    violations = [
        f"{path.relative_to(PROJECT_ROOT).as_posix()} imports {module}"
        for path in sorted(QUERY_INTERFACE_ROOT.rglob("*.py"))
        for module in _absolute_imports(path)
        if _module_matches_root(module, "osu_server.repositories.interfaces.commands")
        or _module_matches_root(module, "osu_server.repositories.interfaces.unit_of_work")
    ]

    assert violations == []


def test_service_facing_sources_do_not_import_low_level_persistence() -> None:
    violations = [
        _format_import_violation(path, forbidden_root, module)
        for root in SERVICE_FACING_SOURCE_ROOTS
        for path in _python_files(root)
        for module in _absolute_imports(path)
        for forbidden_root in FORBIDDEN_SERVICE_FACING_PERSISTENCE_ROOTS
        if _module_matches_root(module, forbidden_root)
    ]

    assert violations == []


def test_service_facing_tests_do_not_assert_against_persistence_models() -> None:
    violations = [
        _format_import_violation(path, forbidden_root, module)
        for root in SERVICE_FACING_TEST_ROOTS
        for path in _python_files(root)
        for module in _absolute_imports(path)
        for forbidden_root in ("osu_server.repositories.sqlalchemy.models",)
        if _module_matches_root(module, forbidden_root)
    ]

    assert violations == []


def _public_async_methods(repository: type[object]) -> set[str]:
    return {
        name
        for name, _ in inspect.getmembers(repository, inspect.iscoroutinefunction)
        if not name.startswith("_")
    }


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


def _python_files(path: Path) -> tuple[Path, ...]:
    if path.is_file():
        return (path,) if path.suffix == ".py" else ()
    if not path.exists():
        return ()
    return tuple(
        sorted(
            candidate for candidate in path.rglob("*.py") if "__pycache__" not in candidate.parts
        )
    )


def _format_import_violation(path: Path, forbidden_root: str, module: str) -> str:
    return f"{path.relative_to(PROJECT_ROOT).as_posix()} imports {forbidden_root} via {module}"


def _module_matches_root(module: str, root: str) -> bool:
    return module == root or module.startswith(f"{root}.")
