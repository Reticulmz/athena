"""Persistence boundary contract tests for command/query repositories."""

from __future__ import annotations

import ast
import inspect
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import get_type_hints

from osu_server.repositories.interfaces.commands import (
    BeatmapCommandRepository,
    BeatmapLeaderboardCommandRepository,
    BeatmapPerformanceBestCommandRepository,
    BlobCommandRepository,
    ChannelCommandRepository,
    ChatCommandRepository,
    CurrentUserStatsCommandRepository,
    FriendRelationshipCommandRepository,
    PersonalBestCommandRepository,
    ReplayCommandRepository,
    RoleCommandRepository,
    ScoreCommandRepository,
    ScorePerformanceCommandRepository,
    ScoreSubmissionCommandRepository,
    UserCommandRepository,
)
from osu_server.repositories.interfaces.queries import (
    BeatmapLeaderboardQueryRepository,
    BeatmapQueryRepository,
    BeatmapScoreListingQueryRepository,
    BlobQueryRepository,
    ChannelQueryRepository,
    ChatHistoryQueryRepository,
    FriendRelationshipQueryRepository,
    LeaderboardReadScope,
    RoleQueryRepository,
    ScorePerformanceQueryRepository,
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
LEADERBOARD_PROJECTION_UPDATE_PATHS = (
    SOURCE_ROOT / "repositories" / "interfaces" / "commands" / "beatmap_leaderboards.py",
    SOURCE_ROOT / "repositories" / "memory" / "commands" / "beatmap_leaderboards.py",
    SOURCE_ROOT / "repositories" / "sqlalchemy" / "commands" / "beatmap_leaderboards.py",
    SOURCE_ROOT / "services" / "commands" / "scores" / "leaderboards",
)

COMMAND_REPOSITORY_ATTRIBUTES = {
    "users": UserCommandRepository,
    "roles": RoleCommandRepository,
    "channels": ChannelCommandRepository,
    "chat": ChatCommandRepository,
    "friends": FriendRelationshipCommandRepository,
    "scores": ScoreCommandRepository,
    "personal_bests": PersonalBestCommandRepository,
    "score_performance": ScorePerformanceCommandRepository,
    "submissions": ScoreSubmissionCommandRepository,
    "replays": ReplayCommandRepository,
    "blobs": BlobCommandRepository,
    "beatmaps": BeatmapCommandRepository,
    "beatmap_leaderboards": BeatmapLeaderboardCommandRepository,
    "beatmap_performance_bests": BeatmapPerformanceBestCommandRepository,
    "current_user_stats": CurrentUserStatsCommandRepository,
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
    FriendRelationshipQueryRepository,
    BeatmapScoreListingQueryRepository,
    ScorePerformanceQueryRepository,
    BeatmapLeaderboardQueryRepository,
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
        FriendRelationshipCommandRepository,
        PersonalBestCommandRepository,
        ScoreCommandRepository,
        ScorePerformanceCommandRepository,
        ScoreSubmissionCommandRepository,
        ReplayCommandRepository,
        BlobCommandRepository,
        BeatmapCommandRepository,
        BeatmapLeaderboardCommandRepository,
        BeatmapPerformanceBestCommandRepository,
        CurrentUserStatsCommandRepository,
    }
    assert _public_async_methods(ScoreCommandRepository) == {
        "create",
        "count_submissions_for_beatmap",
        "exists_by_online_checksum",
        "get_by_id",
        "get_by_online_checksum",
        "increment_replay_view_count",
        "list_current_stats_scores_for_user",
        "list_leaderboard_rebuild_candidates_for_beatmap_ids",
        "list_leaderboard_rebuild_candidates_for_user",
    }
    assert _public_async_methods(PersonalBestCommandRepository) == {
        "get_by_scope",
        "upsert_if_better",
    }
    assert _public_async_methods(FriendRelationshipCommandRepository) == {
        "add_relationship",
        "remove_relationship",
        "target_exists",
    }
    assert _public_async_methods(RoleCommandRepository) == {
        "assign_role",
        "get_by_id",
        "get_by_name",
        "get_default_role",
        "get_roles_for_user",
        "get_user_ids_for_role",
        "set_roles_for_user",
    }
    assert _public_async_methods(BeatmapCommandRepository) >= {
        "save_beatmapset_snapshot",
        "set_local_status_override",
        "increment_submission_counts",
        "try_mark_fetch_pending",
        "mark_fetch_succeeded",
        "mark_fetch_failed",
    }
    assert _public_async_methods(BeatmapLeaderboardCommandRepository) == {
        "get_global_user_best",
        "get_user_best",
        "lock_scope",
        "replace_projection_slice",
        "upsert_if_better",
    }
    assert _public_async_methods(BeatmapPerformanceBestCommandRepository) == {
        "get_best",
        "list_user_bests",
        "lock_scope",
        "replace_projection_slice",
        "replace_scope",
        "upsert_if_better",
    }
    assert _public_async_methods(CurrentUserStatsCommandRepository) == {
        "get",
        "lock_scope",
        "replace",
    }
    assert _public_async_methods(ScorePerformanceCommandRepository) == {
        "claim_pending_calculation",
        "claim_recalculation_work",
        "create_or_reuse_calculation",
        "create_recalculation_batch",
        "get_by_id",
        "get_current_for_score",
        "get_recalculation_batch_by_id",
        "get_recalculation_work_item_by_id",
        "mark_completed",
        "mark_recalculation_work_completed",
        "mark_recalculation_work_failed",
        "mark_recalculation_work_unavailable",
        "mark_unavailable",
        "update_pending_calculation_state",
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
        "get_fetch_state",
    }
    assert _public_async_methods(ScorePerformanceQueryRepository) == {
        "get_current_for_score",
        "select_recalculation_candidates",
    }
    assert _public_async_methods(BeatmapLeaderboardQueryRepository) == {
        "get_personal_best",
        "list_top_rows",
    }
    assert LeaderboardReadScope.__name__ == "LeaderboardReadScope"


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


def test_beatmap_leaderboard_update_path_rejects_legacy_personal_bests() -> None:
    forbidden_roots = (
        "osu_server.domain.scores.personal_best",
        "osu_server.repositories.interfaces.commands.PersonalBestCommandRepository",
        "osu_server.repositories.interfaces.commands.personal_bests",
        "osu_server.repositories.memory.commands.InMemoryPersonalBestCommandRepository",
        "osu_server.repositories.memory.commands.personal_bests",
        "osu_server.repositories.sqlalchemy.commands.SQLAlchemyPersonalBestCommandRepository",
        "osu_server.repositories.sqlalchemy.commands.personal_bests",
    )
    violations = [
        _format_import_violation(path, forbidden_root, module)
        for root in LEADERBOARD_PROJECTION_UPDATE_PATHS
        for path in _python_files(root)
        for module in _absolute_imports(path)
        for forbidden_root in forbidden_roots
        if _module_matches_root(module, forbidden_root)
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
