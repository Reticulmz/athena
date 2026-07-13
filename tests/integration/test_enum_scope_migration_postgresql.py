from __future__ import annotations

import importlib.util
import os
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, async_sessionmaker

from osu_server.domain.beatmaps import (
    BeatmapFileSource,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
)
from osu_server.domain.identity.leaderboard_visibility import (
    LEADERBOARD_VISIBLE_PERMISSION_MASK,
)
from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.performance import FormulaProfile, PerformanceCalculationState
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset
from osu_server.domain.storage.blobs import BlobStorageBackendKind
from osu_server.infrastructure.database.engine import create_engine
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBestScope,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    CompleteScorePerformanceCalculation,
)
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    LeaderboardReadScope,
)
from osu_server.repositories.sqlalchemy.commands.beatmap_leaderboards import (
    SQLAlchemyBeatmapLeaderboardCommandRepository,
)
from osu_server.repositories.sqlalchemy.commands.score_performance import (
    SQLAlchemyScorePerformanceCommandRepository,
)
from osu_server.repositories.sqlalchemy.models.beatmap import (
    BeatmapFileAttachmentModel,
    BeatmapModel,
    BeatmapSetModel,
)
from osu_server.repositories.sqlalchemy.models.beatmap_leaderboard import (
    BeatmapLeaderboardUserBestModel,
)
from osu_server.repositories.sqlalchemy.models.blob import BlobModel
from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel
from osu_server.repositories.sqlalchemy.models.score import ScoreModel
from osu_server.repositories.sqlalchemy.models.score_performance import (
    ScorePerformanceCalculationModel,
)
from osu_server.repositories.sqlalchemy.models.user import UserModel
from osu_server.repositories.sqlalchemy.queries.beatmap_leaderboards import (
    SQLAlchemyBeatmapLeaderboardQueryRepository,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence

    from sqlalchemy.engine import Connection

_MIGRATION_PATH = Path(
    "alembic/versions/20260710_0400_use_enum_types_and_score_based_leaderboards.py"
)
_LEADERBOARD_REPAIR_MIGRATION_PATH = Path(
    "alembic/versions/20260712_0500_repair_legacy_leaderboard_projection.py"
)
_MOD_SCOPED_MIGRATION_PATH = Path(
    "alembic/versions/20260713_0600_add_mod_scoped_leaderboard_projection.py"
)
_ONLINE_INDEX_MIGRATION_PATH = Path(
    "alembic/versions/20260713_0700_create_leaderboard_indexes_concurrently.py"
)
_ENUM_REVISION = "20260710_0400"
_HEAD_REVISION = "20260713_0700"
_PREVIOUS_REVISION = "20260710_0300"
_SCORE_CANDIDATE_INDEX = "idx_scores_beatmap_leaderboard_candidates"
_SCORE_CANDIDATE_COLUMNS = (
    "beatmap_id",
    "ruleset",
    "playstyle",
    "beatmap_checksum",
    "user_id",
    "score",
    "submitted_at",
    "id",
)
_SCORE_CANDIDATE_PREDICATE_COLUMNS = frozenset({"passed", "leaderboard_eligible_at_submission"})
_BEATMAPSET_ID = 1_970_100_001
_BEATMAP_ID = 1_970_100_002
_USER_1_ID = 1_970_000_001
_USER_2_ID = 1_970_000_002
_ROLE_ID = 1_970_000_010
_CURRENT_CHECKSUM = "a" * 32
_STALE_CHECKSUM = "b" * 32
_NOW = datetime(2026, 7, 10, 0, 0, 0, tzinfo=UTC)

_NO_MOD_SCORE_ID = 9_700_000_001
_NIGHTCORE_SCORE_ID = 9_700_000_002
_DOUBLE_TIME_SCORE_ID = 9_700_000_003
_PERFECT_SCORE_ID = 9_700_000_004
_SUDDEN_DEATH_SCORE_ID = 9_700_000_005
_USER_2_NIGHTCORE_SCORE_ID = 9_700_000_006
_STALE_SCORE_ID = 9_700_000_007
_DOUBLE_TIME_LOWER_SCORE_ID = 9_700_000_008
_MIRROR_SCORE_ID = 9_700_000_009
_BLOB_ID = 1_970_200_001
_ATTACHMENT_ID = 9_700_100_001
_OLD_CALCULATION_ID = 9_700_200_001
_REPLACEMENT_CALCULATION_ID = 9_700_200_002
_INVALID_FETCH_TARGET_ID = 9_700_300_001
_INVALID_FETCH_STATUS_ID = 9_700_300_002
_INVALID_SUBMISSION_ID = 9_700_400_001
_INVALID_CALCULATION_STATE_ID = 9_700_500_001
_INVALID_CALCULATION_FORMULA_ID = 9_700_500_002
_SCORE_IDS = (
    _NO_MOD_SCORE_ID,
    _NIGHTCORE_SCORE_ID,
    _DOUBLE_TIME_SCORE_ID,
    _PERFECT_SCORE_ID,
    _SUDDEN_DEATH_SCORE_ID,
    _USER_2_NIGHTCORE_SCORE_ID,
    _STALE_SCORE_ID,
    _DOUBLE_TIME_LOWER_SCORE_ID,
    _MIRROR_SCORE_ID,
)

_CHECKED_ENUM_COLUMNS = (
    ("channels", "channel_type", "ck_channels_channel_type_known", 16),
    ("scores", "grade", "ck_scores_grade_known", 2),
    (
        "scores",
        "beatmap_status_at_submission",
        "ck_beatmap_rank_status_known",
        32,
    ),
    ("scores", "play_time_source", "ck_scores_play_time_source_known", 32),
    ("score_submissions", "state", "ck_score_submissions_state_known", 32),
    ("beatmapsets", "official_status", "ck_beatmap_rank_status_known", 32),
    (
        "beatmapsets",
        "official_status_source",
        "ck_beatmap_metadata_source_known",
        64,
    ),
    ("beatmaps", "mode", "ck_beatmaps_mode_known", 16),
    ("beatmaps", "official_status", "ck_beatmap_rank_status_known", 32),
    (
        "beatmaps",
        "official_status_source",
        "ck_beatmap_metadata_source_known",
        64,
    ),
    (
        "beatmaps",
        "local_status_override",
        "ck_beatmaps_local_status_override_known",
        32,
    ),
    (
        "beatmap_file_attachments",
        "source",
        "ck_beatmap_file_attachments_source_known",
        32,
    ),
    (
        "beatmap_fetch_states",
        "target_type",
        "ck_beatmap_fetch_states_target_type_known",
        32,
    ),
    (
        "beatmap_fetch_states",
        "status",
        "ck_beatmap_fetch_states_status_known",
        32,
    ),
    ("blobs", "storage_backend", "ck_blobs_storage_backend_known", 32),
    ("personal_bests", "category", "ck_personal_bests_category_known", 32),
    (
        "score_performance_calculations",
        "state",
        "ck_score_performance_state_known",
        32,
    ),
    (
        "score_performance_calculations",
        "formula_profile",
        "ck_formula_profile_known",
        64,
    ),
    (
        "performance_recalculation_batches",
        "status",
        "ck_performance_recalculation_batches_status_known",
        32,
    ),
    (
        "performance_recalculation_batches",
        "target_formula_profile",
        "ck_formula_profile_known",
        64,
    ),
    (
        "performance_recalculation_work_items",
        "reason",
        "ck_performance_recalculation_work_items_reason_known",
        64,
    ),
    (
        "performance_recalculation_work_items",
        "state",
        "ck_performance_recalculation_work_items_state_known",
        32,
    ),
)


class _MigrationModule(Protocol):
    op: Operations

    def upgrade(self) -> None: ...

    def downgrade(self) -> None: ...


def _load_migration() -> _MigrationModule:
    spec = importlib.util.spec_from_file_location("enum_scope_migration", _MIGRATION_PATH)
    if spec is None or spec.loader is None:
        msg = f"could not load migration: {_MIGRATION_PATH}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("_MigrationModule", cast("object", module))


_MIGRATION = _load_migration()


def _load_leaderboard_repair_migration() -> _MigrationModule:
    spec = importlib.util.spec_from_file_location(
        "leaderboard_projection_repair_migration",
        _LEADERBOARD_REPAIR_MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        msg = f"could not load migration: {_LEADERBOARD_REPAIR_MIGRATION_PATH}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("_MigrationModule", cast("object", module))


def _load_mod_scoped_migration() -> _MigrationModule:
    spec = importlib.util.spec_from_file_location(
        "mod_scoped_leaderboard_projection_migration",
        _MOD_SCOPED_MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        msg = f"could not load migration: {_MOD_SCOPED_MIGRATION_PATH}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("_MigrationModule", cast("object", module))


_MOD_SCOPED_MIGRATION = _load_mod_scoped_migration()


def _load_online_index_migration() -> _MigrationModule:
    spec = importlib.util.spec_from_file_location(
        "online_leaderboard_index_migration",
        _ONLINE_INDEX_MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        msg = f"could not load migration: {_ONLINE_INDEX_MIGRATION_PATH}"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("_MigrationModule", cast("object", module))


_ONLINE_INDEX_MIGRATION = _load_online_index_migration()


def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture
async def postgres_engine() -> AsyncGenerator[AsyncEngine]:
    """実PostgreSQLへ接続するtest engineを提供する.

    Yields:
        AsyncEngine: 接続確認済みの非同期engine.

    Raises:
        pytest.skip: DATABASE_URLが未設定または接続不能な場合.

    Notes:
        fixture終了時にengineをdisposeする.
    """
    engine = create_engine(_get_database_url())
    try:
        async with engine.connect() as connection:
            _ = await connection.execute(sa.select(sa.literal(1)))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"DATABASE_URL is set but database is unavailable: {exc}")
    yield engine
    await engine.dispose()


@pytest.fixture
async def postgres_connection(
    postgres_engine: AsyncEngine,
) -> AsyncGenerator[AsyncConnection]:
    """Migration test専用schemaへ接続するconnectionを提供する.

    Args:
        postgres_engine (AsyncEngine): 実PostgreSQLへ接続するtest engine.

    Yields:
        AsyncConnection: head migration適用済みの専用schema接続.

    Raises:
        SQLAlchemyError: schema作成, migration適用, またはcleanupに失敗した場合.

    Notes:
        Concurrent DDLがtransactionをcommitするため, fixture終了時に専用schemaを
        明示的にdropしてtest dataを破棄する.
    """
    async with postgres_engine.connect() as connection:
        schema_name = f"athena_enum_scope_{secrets.token_hex(8)}"
        schema_created = False
        try:
            _ = await connection.execute(sa.schema.CreateSchema(schema_name))
            await connection.commit()
            schema_created = True
            _ = await connection.execute(
                sa.select(sa.func.set_config("search_path", schema_name, False))
            )
            await connection.commit()
            await connection.run_sync(_upgrade_schema_to_head)
            yield connection
        finally:
            if connection.in_transaction():
                await connection.rollback()
            if schema_created:
                _ = await connection.execute(
                    sa.select(sa.func.set_config("search_path", "public", False))
                )
                await connection.commit()
                _ = await connection.execute(sa.schema.DropSchema(schema_name, cascade=True))
                await connection.commit()


@pytest.fixture
async def postgres_connection_at_enum_revision(
    postgres_engine: AsyncEngine,
) -> AsyncGenerator[AsyncConnection]:
    """0400 migration適用済みの専用schema接続を提供する.

    Args:
        postgres_engine (AsyncEngine): 実PostgreSQLへ接続するtest engine.

    Yields:
        AsyncConnection: `20260710_0400`まで適用した専用schema接続.

    Raises:
        SQLAlchemyError: schema作成, migration適用, またはcleanupに失敗した場合.

    Notes:
        0500のconcurrent DDLがtransactionをcommitするため, fixture終了時に
        専用schemaを明示的にdropしてtest dataを破棄する.
    """
    async with postgres_engine.connect() as connection:
        schema_name = f"athena_enum_scope_revision_{secrets.token_hex(8)}"
        schema_created = False
        try:
            _ = await connection.execute(sa.schema.CreateSchema(schema_name))
            await connection.commit()
            schema_created = True
            _ = await connection.execute(
                sa.select(sa.func.set_config("search_path", schema_name, False))
            )
            await connection.commit()
            await connection.run_sync(
                lambda sync_connection: _upgrade_schema_to_revision(
                    sync_connection,
                    _ENUM_REVISION,
                )
            )
            yield connection
        finally:
            if connection.in_transaction():
                await connection.rollback()
            if schema_created:
                _ = await connection.execute(
                    sa.select(sa.func.set_config("search_path", "public", False))
                )
                await connection.commit()
                _ = await connection.execute(sa.schema.DropSchema(schema_name, cascade=True))
                await connection.commit()


@pytest.fixture
async def postgres_connection_before_enum_migration(
    postgres_engine: AsyncEngine,
) -> AsyncGenerator[AsyncConnection]:
    """Enum migration直前の専用schema接続を提供する.

    Args:
        postgres_engine (AsyncEngine): 実PostgreSQLへ接続するtest engine.

    Yields:
        AsyncConnection: `20260710_0300`まで適用した専用schema接続.

    Notes:
        fixture終了時にtransactionをrollbackして専用schemaを破棄する.
    """
    async with postgres_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            schema_name = f"athena_enum_scope_previous_{secrets.token_hex(8)}"
            _ = await connection.execute(sa.schema.CreateSchema(schema_name))
            _ = await connection.execute(
                sa.select(sa.func.set_config("search_path", schema_name, True))
            )
            await connection.run_sync(
                lambda sync_connection: _upgrade_schema_to_revision(
                    sync_connection,
                    _PREVIOUS_REVISION,
                )
            )
            yield connection
        finally:
            if transaction.is_active:
                await transaction.rollback()


async def test_postgresql_enum_columns_use_checked_strings(
    postgres_connection: AsyncConnection,
) -> None:
    """Enum列がVARCHARと名前付きCHECKで永続化されることを検証する.

    Args:
        postgres_connection (AsyncConnection): 専用schemaへ接続した非同期接続.

    Returns:
        None: 全対象列の文字列型、長さ、CHECK拒否を検証したことを示す.

    Raises:
        AssertionError: native Enum、CHECK欠落、長さ不一致、または不正値受理の場合.
    """
    await _seed_fixture(postgres_connection)
    await postgres_connection.run_sync(_assert_checked_enum_storage)

    scores = sa.table(
        "scores",
        sa.column("id", sa.BigInteger()),
        sa.column("grade", sa.String(length=2)),
        sa.column("play_time_source", sa.String(length=32)),
    )
    fetch_states = sa.table(
        "beatmap_fetch_states",
        sa.column("id", sa.BigInteger()),
        sa.column("target_type", sa.String(length=32)),
        sa.column("target_key", sa.String(length=255)),
        sa.column("status", sa.String(length=32)),
    )
    submissions = sa.table(
        "score_submissions",
        sa.column("id", sa.BigInteger()),
        sa.column("fingerprint", sa.String(length=64)),
        sa.column("user_id", sa.Integer()),
        sa.column("beatmap_checksum", sa.String(length=32)),
        sa.column("state", sa.String(length=32)),
    )
    calculations = sa.table(
        "score_performance_calculations",
        sa.column("id", sa.BigInteger()),
        sa.column("score_id", sa.BigInteger()),
        sa.column("state", sa.String(length=32)),
        sa.column("is_current", sa.Boolean()),
        sa.column("calculator_name", sa.String(length=64)),
        sa.column("calculator_version", sa.String(length=64)),
        sa.column("formula_profile", sa.String(length=64)),
    )
    invalid_writes = (
        (
            sa.update(scores).where(scores.c.id == _NO_MOD_SCORE_ID).values(grade="ZZ"),
            "ck_scores_grade_known",
        ),
        (
            sa.update(scores)
            .where(scores.c.id == _NO_MOD_SCORE_ID)
            .values(play_time_source="unknown_source"),
            "ck_scores_play_time_source_known",
        ),
        (
            sa.insert(fetch_states).values(
                id=_INVALID_FETCH_TARGET_ID,
                target_type="unknown_target",
                target_key="invalid-target",
                status="fresh",
            ),
            "ck_beatmap_fetch_states_target_type_known",
        ),
        (
            sa.insert(fetch_states).values(
                id=_INVALID_FETCH_STATUS_ID,
                target_type="metadata:beatmap",
                target_key="invalid-status",
                status="unknown_status",
            ),
            "ck_beatmap_fetch_states_status_known",
        ),
        (
            sa.insert(submissions).values(
                id=_INVALID_SUBMISSION_ID,
                fingerprint="invalid-enum-state",
                user_id=_USER_1_ID,
                beatmap_checksum=_CURRENT_CHECKSUM,
                state="unknown_state",
            ),
            "ck_score_submissions_state_known",
        ),
        (
            sa.insert(calculations).values(
                id=_INVALID_CALCULATION_STATE_ID,
                score_id=_NO_MOD_SCORE_ID,
                state="unknown_state",
                is_current=False,
                calculator_name="enum-check",
                calculator_version="1",
                formula_profile=FormulaProfile.VANILLA_RANKED.value,
            ),
            "ck_score_performance_state_known",
        ),
        (
            sa.insert(calculations).values(
                id=_INVALID_CALCULATION_FORMULA_ID,
                score_id=_NO_MOD_SCORE_ID,
                state=PerformanceCalculationState.QUEUED.value,
                is_current=False,
                calculator_name="enum-check",
                calculator_version="1",
                formula_profile="unknown_formula",
            ),
            "ck_formula_profile_known",
        ),
    )

    for statement, constraint_name in invalid_writes:
        savepoint = await postgres_connection.begin_nested()
        try:
            with pytest.raises(IntegrityError, match=constraint_name):
                _ = await postgres_connection.execute(statement)
        finally:
            await savepoint.rollback()


async def test_postgresql_migration_rejects_preexisting_unknown_enum_value(
    postgres_connection_before_enum_migration: AsyncConnection,
) -> None:
    """Migration前の未定義値を黙って制約化しないことを検証する.

    Args:
        postgres_connection_before_enum_migration (AsyncConnection):
            Enum migration直前の専用schema接続.

    Returns:
        None: upgradeが未定義値を検出して停止したことを示す.

    Raises:
        AssertionError: 未定義値を保持したままupgradeが成功した場合.
    """
    submissions = sa.table(
        "score_submissions",
        sa.column("id", sa.BigInteger()),
        sa.column("fingerprint", sa.String(length=64)),
        sa.column("user_id", sa.Integer()),
        sa.column("beatmap_checksum", sa.String(length=32)),
        sa.column("state", sa.String(length=32)),
    )
    _ = await postgres_connection_before_enum_migration.execute(
        sa.insert(submissions).values(
            id=_INVALID_SUBMISSION_ID,
            fingerprint="pre-migration-invalid-enum-state",
            user_id=_USER_1_ID,
            beatmap_checksum=_CURRENT_CHECKSUM,
            state="unknown_state",
        )
    )

    with pytest.raises(
        RuntimeError,
        match=(
            r"score_submissions\.state contains values outside "
            r"ck_score_submissions_state_known"
        ),
    ):
        await postgres_connection_before_enum_migration.run_sync(_run_upgrade)


async def test_postgresql_exact_selected_mod_predicates_and_projection_ranking(
    postgres_connection: AsyncConnection,
) -> None:
    """raw Mod完全一致とprojection起点のrankingを確認する.

    Args:
        postgres_connection (AsyncConnection): 専用schemaへ接続した非同期接続.

    Returns:
        None: GlobalとSelected Modsのrankingが期待値と一致したことを示す.

    Raises:
        AssertionError: filter, ranking, またはprojection更新結果が異なる場合.

    Notes:
        Globalはmodsを無視し, Selected Modsだけprojectionのmodsで完全一致する.
    """
    await _seed_fixture(postgres_connection)
    await postgres_connection.run_sync(_run_mod_scoped_downgrade)
    await postgres_connection.run_sync(_run_mod_scoped_upgrade)

    session_factory = async_sessionmaker(
        postgres_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    query_repository = SQLAlchemyBeatmapLeaderboardQueryRepository(session_factory)

    global_rows = await query_repository.list_top_rows(
        _read_scope(LeaderboardCategory.GLOBAL),
        limit=50,
    )
    double_time_rows = await query_repository.list_top_rows(
        _read_scope(
            LeaderboardCategory.SELECTED_MODS,
            selected_mods=ModCombination.from_bitmask(int(Mod.DOUBLE_TIME)),
        ),
        limit=50,
    )
    nightcore_rows = await query_repository.list_top_rows(
        _read_scope(
            LeaderboardCategory.SELECTED_MODS,
            selected_mods=ModCombination.from_bitmask(int(Mod.NIGHTCORE | Mod.DOUBLE_TIME)),
        ),
        limit=50,
    )
    sudden_death_rows = await query_repository.list_top_rows(
        _read_scope(
            LeaderboardCategory.SELECTED_MODS,
            selected_mods=ModCombination.from_bitmask(int(Mod.SUDDEN_DEATH)),
        ),
        limit=50,
    )
    perfect_rows = await query_repository.list_top_rows(
        _read_scope(
            LeaderboardCategory.SELECTED_MODS,
            selected_mods=ModCombination.from_bitmask(int(Mod.PERFECT | Mod.SUDDEN_DEATH)),
        ),
        limit=50,
    )
    mirror_rows = await query_repository.list_top_rows(
        _read_scope(
            LeaderboardCategory.SELECTED_MODS,
            selected_mods=ModCombination.from_bitmask(int(Mod.MIRROR)),
        ),
        limit=50,
    )
    no_mod_rows = await query_repository.list_top_rows(
        _read_scope(
            LeaderboardCategory.SELECTED_MODS,
            selected_mods=ModCombination.none(),
        ),
        limit=50,
    )

    assert [(row.score_id, row.rank) for row in global_rows] == [
        (_USER_2_NIGHTCORE_SCORE_ID, 1),
        (_NO_MOD_SCORE_ID, 2),
    ]
    assert [row.score_id for row in double_time_rows] == [_DOUBLE_TIME_SCORE_ID]
    assert [row.score_id for row in nightcore_rows] == [
        _USER_2_NIGHTCORE_SCORE_ID,
        _NIGHTCORE_SCORE_ID,
    ]
    assert [row.score_id for row in sudden_death_rows] == [_SUDDEN_DEATH_SCORE_ID]
    assert [row.score_id for row in perfect_rows] == [_PERFECT_SCORE_ID]
    assert [row.score_id for row in mirror_rows] == [_MIRROR_SCORE_ID]
    assert [row.score_id for row in no_mod_rows] == [_NO_MOD_SCORE_ID]

    async with session_factory() as session:
        command_repository = SQLAlchemyBeatmapLeaderboardCommandRepository(session)
        _ = await command_repository.upsert_if_better(
            _projection_upsert(
                beatmap_checksum=_STALE_CHECKSUM,
                score_id=_STALE_SCORE_ID,
                score=9_999,
                submitted_at=_NOW + timedelta(seconds=6),
            )
        )
        current = await command_repository.upsert_if_better(
            _projection_upsert(
                beatmap_checksum=_CURRENT_CHECKSUM,
                score_id=_NO_MOD_SCORE_ID,
                score=1_000,
                submitted_at=_NOW,
            )
        )

    assert current.score_id == _NO_MOD_SCORE_ID
    assert current.scope.beatmap_checksum == _CURRENT_CHECKSUM


async def test_postgresql_claimed_replacement_completion_clears_claims_before_flush(
    postgres_connection: AsyncConnection,
) -> None:
    """claim中のreplacementを制約違反なしで完了できることを確認する.

    Args:
        postgres_connection (AsyncConnection): 専用schemaへ接続した非同期接続.

    Returns:
        None: replacementと旧currentのclaim pairがterminal化前に解除されたことを示す.

    Raises:
        AssertionError: 完了結果またはclaim lifecycleが期待値と異なる場合.

    Notes:
        実PostgreSQLのclaim metadata制約を通して最初のflush順序を検証する.
    """
    await _seed_fixture(postgres_connection)

    session_factory = async_sessionmaker(
        postgres_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    async with session_factory() as session:
        blob = BlobModel(
            id=_BLOB_ID,
            sha256="c" * 64,
            byte_size=1,
            content_type="application/octet-stream",
            storage_backend=BlobStorageBackendKind.LOCAL.value,
            storage_key="enum-scope/performance-test.osu",
        )
        attachment = BeatmapFileAttachmentModel(
            id=_ATTACHMENT_ID,
            beatmap_id=_BEATMAP_ID,
            blob_id=_BLOB_ID,
            checksum_md5=_CURRENT_CHECKSUM,
            verified_md5=_CURRENT_CHECKSUM,
            source=BeatmapFileSource.OFFICIAL.value,
            original_filename="performance-test.osu",
            fetched_at=_NOW,
            verified_at=_NOW,
        )
        old_current = ScorePerformanceCalculationModel(
            id=_OLD_CALCULATION_ID,
            score_id=_NO_MOD_SCORE_ID,
            state=PerformanceCalculationState.CALCULATING.value,
            is_current=True,
            pp=None,
            star_rating=None,
            calculator_name="rosu-pp-py",
            calculator_version="4.0.2",
            formula_profile=FormulaProfile.VANILLA_RANKED.value,
            beatmap_file_attachment_id=None,
            beatmap_file_checksum_md5=None,
            unavailable_reason=None,
            claim_owner="old-worker",
            claim_expires_at=_NOW + timedelta(minutes=5),
            attempt_count=1,
            calculated_at=None,
        )
        replacement = ScorePerformanceCalculationModel(
            id=_REPLACEMENT_CALCULATION_ID,
            score_id=_NO_MOD_SCORE_ID,
            state=PerformanceCalculationState.CALCULATING.value,
            is_current=False,
            pp=None,
            star_rating=None,
            calculator_name="rosu-pp-py",
            calculator_version="4.1.0",
            formula_profile=FormulaProfile.VANILLA_RANKED.value,
            beatmap_file_attachment_id=None,
            beatmap_file_checksum_md5=None,
            unavailable_reason=None,
            claim_owner="replacement-worker",
            claim_expires_at=_NOW + timedelta(minutes=5),
            attempt_count=1,
            calculated_at=None,
        )
        session.add(blob)
        await session.flush()
        session.add(attachment)
        await session.flush()
        session.add_all((old_current, replacement))
        await session.flush()

        repository = SQLAlchemyScorePerformanceCommandRepository(session)
        completed = await repository.mark_completed(
            CompleteScorePerformanceCalculation(
                calculation_id=_REPLACEMENT_CALCULATION_ID,
                pp=Decimal("222.222222"),
                star_rating=Decimal("6.54321"),
                calculator_name="rosu-pp-py",
                calculator_version="4.1.0",
                formula_profile=FormulaProfile.VANILLA_RANKED,
                beatmap_file_attachment_id=_ATTACHMENT_ID,
                beatmap_file_checksum_md5=_CURRENT_CHECKSUM,
                calculated_at=_NOW,
            )
        )

        assert completed is not None
        assert completed.state is PerformanceCalculationState.COMPLETED
        assert completed.is_current is True
        assert replacement.claim_owner is None
        assert replacement.claim_expires_at is None
        assert old_current.state == PerformanceCalculationState.SUPERSEDED.value
        assert old_current.is_current is False
        assert old_current.claim_owner is None
        assert old_current.claim_expires_at is None


async def test_postgresql_migration_round_trip_restores_legacy_projection(
    postgres_connection_at_enum_revision: AsyncConnection,
) -> None:
    """migration往復後にlegacy projectionと現行projectionを復元できるか確認する.

    Args:
        postgres_connection (AsyncConnection): 専用schemaへ接続した非同期接続.

    Returns:
        None: downgradeと再upgrade後のprojectionが期待値と一致したことを示す.

    Raises:
        AssertionError: legacy行または再構築した現行行が期待値と異なる場合.

    Notes:
        stale checksumの旧Global行はcurrent checksumのsource scoreから再構築する.
    """
    connection = postgres_connection_at_enum_revision
    await _seed_fixture(connection)

    await connection.run_sync(_run_downgrade)

    assert set(await _legacy_projection_rows(connection)) == {
        (_USER_1_ID, None, _NO_MOD_SCORE_ID),
        (_USER_1_ID, 0, _NO_MOD_SCORE_ID),
        (_USER_1_ID, int(Mod.SUDDEN_DEATH), _SUDDEN_DEATH_SCORE_ID),
        (_USER_1_ID, int(Mod.DOUBLE_TIME), _DOUBLE_TIME_SCORE_ID),
        (_USER_2_ID, None, _USER_2_NIGHTCORE_SCORE_ID),
        (_USER_2_ID, int(Mod.DOUBLE_TIME), _USER_2_NIGHTCORE_SCORE_ID),
    }

    await _replace_legacy_global_with_stale_score(connection)
    await connection.run_sync(_run_upgrade)

    assert set(await _global_projection_rows(connection)) == {
        (_USER_1_ID, _CURRENT_CHECKSUM, _NO_MOD_SCORE_ID),
        (_USER_2_ID, _CURRENT_CHECKSUM, _USER_2_NIGHTCORE_SCORE_ID),
    }


async def test_postgresql_mod_scoped_migration_round_trip_rebuilds_projection(
    postgres_connection: AsyncConnection,
) -> None:
    """0600往復時にGlobalとraw Mod別projectionを再構築する.

    Args:
        postgres_connection (AsyncConnection): 0600適用済みの専用schema接続.

    Returns:
        None: downgrade後のGlobal行と再upgrade後のMod別行が一致したことを示す.

    Raises:
        AssertionError: schemaまたは再構築結果が期待値と異なる場合.
    """
    await _seed_fixture(postgres_connection)

    await postgres_connection.run_sync(_run_online_index_downgrade)
    await postgres_connection.run_sync(_run_mod_scoped_downgrade)

    assert set(await _global_projection_rows(postgres_connection)) == {
        (_USER_1_ID, _CURRENT_CHECKSUM, _NO_MOD_SCORE_ID),
        (_USER_2_ID, _CURRENT_CHECKSUM, _USER_2_NIGHTCORE_SCORE_ID),
    }

    await postgres_connection.run_sync(_run_mod_scoped_upgrade)
    await postgres_connection.run_sync(_run_online_index_upgrade)

    assert set(await _mod_scoped_projection_rows(postgres_connection)) == {
        (_USER_1_ID, _CURRENT_CHECKSUM, int(Mod.NONE), _NO_MOD_SCORE_ID),
        (
            _USER_1_ID,
            _CURRENT_CHECKSUM,
            int(Mod.NIGHTCORE | Mod.DOUBLE_TIME),
            _NIGHTCORE_SCORE_ID,
        ),
        (_USER_1_ID, _CURRENT_CHECKSUM, int(Mod.DOUBLE_TIME), _DOUBLE_TIME_SCORE_ID),
        (
            _USER_1_ID,
            _CURRENT_CHECKSUM,
            int(Mod.PERFECT | Mod.SUDDEN_DEATH),
            _PERFECT_SCORE_ID,
        ),
        (_USER_1_ID, _CURRENT_CHECKSUM, int(Mod.SUDDEN_DEATH), _SUDDEN_DEATH_SCORE_ID),
        (_USER_1_ID, _CURRENT_CHECKSUM, int(Mod.MIRROR), _MIRROR_SCORE_ID),
        (
            _USER_2_ID,
            _CURRENT_CHECKSUM,
            int(Mod.NIGHTCORE | Mod.DOUBLE_TIME),
            _USER_2_NIGHTCORE_SCORE_ID,
        ),
    }

    columns, unique_constraints, check_constraints, indexes = await postgres_connection.run_sync(
        _read_mod_scoped_projection_schema
    )
    assert "mod_filter_key" not in columns
    assert "mods" in columns
    assert unique_constraints["uq_beatmap_leaderboard_user_bests_scope"] == (
        "beatmap_id",
        "ruleset",
        "playstyle",
        "user_id",
        "mods",
    )
    assert unique_constraints["uq_beatmap_leaderboard_user_bests_score_id"] == ("score_id",)
    assert "ck_beatmap_leaderboard_user_bests_mods_non_negative" in check_constraints
    assert "idx_beatmap_leaderboard_user_bests_global_rank" in indexes
    assert "idx_beatmap_leaderboard_user_bests_mod_rank" in indexes


async def test_successor_migration_repairs_duplicate_legacy_projection_rows(
    postgres_connection_at_enum_revision: AsyncConnection,
) -> None:
    """同一score_idの旧Global/Selected Mods行をGlobal 1行へ修復する.

    Args:
        postgres_connection (AsyncConnection): 0400適用済みの専用schema接続.

    Returns:
        None: 後続migrationが旧2行構造をcanonical projectionへ修復したことを示す.

    Raises:
        AssertionError: migration欠落, 重複残存, またはcanonical制約欠落の場合.
    """
    connection = postgres_connection_at_enum_revision
    await _seed_fixture(connection)
    await connection.run_sync(_replace_projection_with_legacy_duplicate_rows)

    assert set(await _legacy_projection_rows(connection)) == {
        (_USER_1_ID, None, _NO_MOD_SCORE_ID),
        (_USER_1_ID, 0, _NO_MOD_SCORE_ID),
    }
    assert _LEADERBOARD_REPAIR_MIGRATION_PATH.exists()

    repair_migration = _load_leaderboard_repair_migration()
    await connection.run_sync(
        lambda sync_connection: _run_migration_upgrade(
            sync_connection,
            repair_migration,
        )
    )

    assert set(await _global_projection_rows(connection)) == {
        (_USER_1_ID, _CURRENT_CHECKSUM, _NO_MOD_SCORE_ID),
        (_USER_2_ID, _CURRENT_CHECKSUM, _USER_2_NIGHTCORE_SCORE_ID),
    }
    columns, unique_constraints = await connection.run_sync(_read_projection_schema)
    assert "mod_filter_key" not in columns
    assert "beatmap_checksum" in columns
    assert "uq_beatmap_leaderboard_user_bests_scope" in unique_constraints
    assert "uq_beatmap_leaderboard_user_bests_score_id" in unique_constraints


async def test_successor_migration_preserves_canonical_projection(
    postgres_connection_at_enum_revision: AsyncConnection,
) -> None:
    """Canonicalな0400 projectionを後続migrationが再作成しないことを確認する.

    Args:
        postgres_connection (AsyncConnection): 0400適用済みの専用schema接続.

    Returns:
        None: canonical rowのidentityが維持されたことを示す.

    Raises:
        AssertionError: migrationがcanonical tableを不要に再作成した場合.
    """
    connection = postgres_connection_at_enum_revision
    await _seed_fixture(connection)
    canonical_row_id = 9_700_900_001
    _ = await connection.execute(
        sa.insert(BeatmapLeaderboardUserBestModel),
        [
            {
                "id": canonical_row_id,
                "beatmap_id": _BEATMAP_ID,
                "beatmap_checksum": _CURRENT_CHECKSUM,
                "ruleset": Ruleset.OSU.value,
                "playstyle": Playstyle.VANILLA.value,
                "user_id": _USER_1_ID,
                "score_id": _NO_MOD_SCORE_ID,
                "score": 1_000_000,
                "submitted_at": _NOW,
            }
        ],
    )
    identity_statement = sa.select(
        BeatmapLeaderboardUserBestModel.id,
        BeatmapLeaderboardUserBestModel.user_id,
        BeatmapLeaderboardUserBestModel.score_id,
    ).order_by(BeatmapLeaderboardUserBestModel.id)
    before = tuple((await connection.execute(identity_statement)).tuples())

    repair_migration = _load_leaderboard_repair_migration()
    await connection.run_sync(
        lambda sync_connection: _run_migration_upgrade(
            sync_connection,
            repair_migration,
        )
    )

    after = tuple((await connection.execute(identity_statement)).tuples())
    assert before == after == ((canonical_row_id, _USER_1_ID, _NO_MOD_SCORE_ID),)


async def test_successor_migration_replaces_misdefined_score_candidate_index(
    postgres_connection_at_enum_revision: AsyncConnection,
) -> None:
    """0500が同名の誤定義candidate indexをcanonical定義へ置換するか確認する.

    Args:
        postgres_connection_at_enum_revision (AsyncConnection): 0400適用済みの専用接続.

    Returns:
        None: 0500適用後のindex定義とPostgreSQL validityが一致したことを示す.

    Raises:
        AssertionError: index定義, predicate, sort, またはvalidityが期待値と異なる場合.
        SQLAlchemyError: index置換またはmigration実行に失敗した場合.
    """
    connection = postgres_connection_at_enum_revision
    await connection.run_sync(_replace_score_candidate_index_with_wrong_definition)

    repair_migration = _load_leaderboard_repair_migration()
    await connection.run_sync(
        lambda sync_connection: _run_migration_upgrade(
            sync_connection,
            repair_migration,
        )
    )

    await connection.run_sync(_assert_score_candidate_index_is_current)


async def test_online_index_migration_repairs_invalid_score_candidate_index(
    postgres_connection: AsyncConnection,
) -> None:
    """0700が失敗したconcurrent build由来のINVALID indexを修復するか確認する.

    Args:
        postgres_connection (AsyncConnection): 0700適用済みの専用接続.

    Returns:
        None: 0700再適用後のindex定義とPostgreSQL validityが一致したことを示す.

    Raises:
        AssertionError: INVALID indexを生成できない場合または修復結果が異なる場合.
        SQLAlchemyError: index置換またはmigration実行に失敗した場合.
    """
    await _seed_fixture(postgres_connection)
    await postgres_connection.run_sync(_run_online_index_downgrade)
    await postgres_connection.run_sync(_replace_score_candidate_index_with_invalid_definition)
    await postgres_connection.run_sync(_run_online_index_upgrade)

    await postgres_connection.run_sync(_assert_score_candidate_index_is_current)


async def test_online_index_migration_preserves_equivalent_score_candidate_index(
    postgres_connection: AsyncConnection,
) -> None:
    """0700が意味的に同値なcandidate indexを再構築しないことを確認する.

    Args:
        postgres_connection (AsyncConnection): 0700適用済みの専用接続.

    Returns:
        None: predicate順序とNULL並びが異なる同値indexのOID維持を示す.

    Raises:
        AssertionError: 0700が同値indexを不要に再構築した場合.
        SQLAlchemyError: index置換, catalog参照, またはmigration実行に失敗した場合.
    """
    await postgres_connection.run_sync(_run_online_index_downgrade)
    await postgres_connection.run_sync(_replace_score_candidate_index_with_equivalent_definition)
    before_oid = await postgres_connection.run_sync(_read_score_candidate_index_oid)

    await postgres_connection.run_sync(_run_online_index_upgrade)

    after_oid = await postgres_connection.run_sync(_read_score_candidate_index_oid)
    assert after_oid == before_oid


def _upgrade_schema_to_head(connection: Connection) -> None:
    _upgrade_schema_to_revision(connection, _HEAD_REVISION)


def _upgrade_schema_to_revision(connection: Connection, revision_id: str) -> None:
    migration_context = MigrationContext.configure(
        connection,
        opts={"transaction_per_migration": True},
    )
    operations = Operations(migration_context)
    script_directory = ScriptDirectory.from_config(Config("alembic.ini"))
    revisions = tuple(script_directory.walk_revisions(base="base", head=revision_id))
    for revision in reversed(revisions):
        migration = cast("_MigrationModule", cast("object", revision.module))
        migration.op = operations
        with migration_context.begin_transaction(_per_migration=True):
            migration.upgrade()


def _run_downgrade(connection: Connection) -> None:
    _MIGRATION.op = Operations(MigrationContext.configure(connection))
    _MIGRATION.downgrade()


def _run_upgrade(connection: Connection) -> None:
    _MIGRATION.op = Operations(MigrationContext.configure(connection))
    _MIGRATION.upgrade()


def _run_mod_scoped_downgrade(connection: Connection) -> None:
    _MOD_SCOPED_MIGRATION.op = Operations(MigrationContext.configure(connection))
    _MOD_SCOPED_MIGRATION.downgrade()


def _run_mod_scoped_upgrade(connection: Connection) -> None:
    _MOD_SCOPED_MIGRATION.op = Operations(MigrationContext.configure(connection))
    _MOD_SCOPED_MIGRATION.upgrade()


def _run_online_index_downgrade(connection: Connection) -> None:
    if connection.in_transaction():
        connection.commit()
    migration_context = MigrationContext.configure(
        connection,
        opts={"transaction_per_migration": True},
    )
    _ONLINE_INDEX_MIGRATION.op = Operations(migration_context)
    with migration_context.begin_transaction(_per_migration=True):
        _ONLINE_INDEX_MIGRATION.downgrade()


def _run_online_index_upgrade(connection: Connection) -> None:
    if connection.in_transaction():
        connection.commit()
    migration_context = MigrationContext.configure(
        connection,
        opts={"transaction_per_migration": True},
    )
    _ONLINE_INDEX_MIGRATION.op = Operations(migration_context)
    with migration_context.begin_transaction(_per_migration=True):
        _ONLINE_INDEX_MIGRATION.upgrade()


def _run_migration_upgrade(
    connection: Connection,
    migration: _MigrationModule,
) -> None:
    if connection.in_transaction():
        connection.commit()
    migration_context = MigrationContext.configure(
        connection,
        opts={"transaction_per_migration": True},
    )
    migration.op = Operations(migration_context)
    with migration_context.begin_transaction(_per_migration=True):
        migration.upgrade()


def _replace_score_candidate_index_with_wrong_definition(connection: Connection) -> None:
    operations = Operations(MigrationContext.configure(connection))
    operations.drop_index(
        _SCORE_CANDIDATE_INDEX,
        table_name="scores",
        if_exists=True,
    )
    operations.create_index(
        _SCORE_CANDIDATE_INDEX,
        "scores",
        ["beatmap_id"],
    )


def _replace_score_candidate_index_with_invalid_definition(connection: Connection) -> None:
    if connection.in_transaction():
        connection.commit()
    migration_context = MigrationContext.configure(
        connection,
        opts={"transaction_per_migration": True},
    )
    operations = Operations(migration_context)
    with (
        migration_context.begin_transaction(_per_migration=True),
        migration_context.autocommit_block(),
    ):
        operations.drop_index(
            _SCORE_CANDIDATE_INDEX,
            table_name="scores",
            if_exists=True,
            postgresql_concurrently=True,
        )
        with pytest.raises(IntegrityError):
            operations.create_index(
                _SCORE_CANDIDATE_INDEX,
                "scores",
                ["beatmap_id"],
                unique=True,
                postgresql_concurrently=True,
            )

    validity = _read_score_candidate_index_validity(connection)
    assert validity is not None
    assert validity[0] is False


def _replace_score_candidate_index_with_equivalent_definition(connection: Connection) -> None:
    operations = Operations(MigrationContext.configure(connection))
    operations.drop_index(
        _SCORE_CANDIDATE_INDEX,
        table_name="scores",
        if_exists=True,
    )
    operations.create_index(
        _SCORE_CANDIDATE_INDEX,
        "scores",
        [
            "beatmap_id",
            "ruleset",
            "playstyle",
            "beatmap_checksum",
            "user_id",
            sa.column("score", sa.Integer()).desc().nulls_last(),
            sa.column("submitted_at", sa.DateTime(timezone=True)).asc(),
            sa.column("id", sa.BigInteger()).asc(),
        ],
        postgresql_where=sa.and_(
            sa.column("leaderboard_eligible_at_submission", sa.Boolean()).is_(True),
            sa.column("passed", sa.Boolean()).is_(True),
        ),
    )


def _assert_score_candidate_index_is_current(connection: Connection) -> None:
    inspector = sa.inspect(connection)
    candidate_index = next(
        (
            index
            for index in inspector.get_indexes("scores")
            if index["name"] == _SCORE_CANDIDATE_INDEX
        ),
        None,
    )
    assert candidate_index is not None
    assert candidate_index["unique"] is False
    assert tuple(str(name) for name in candidate_index["column_names"]) == (
        _SCORE_CANDIDATE_COLUMNS
    )
    column_sorting = {
        str(name): tuple(str(option) for option in options)
        for name, options in candidate_index.get("column_sorting", {}).items()
    }
    assert "desc" in column_sorting["score"]
    assert all(
        "desc" not in options
        for column_name, options in column_sorting.items()
        if column_name != "score"
    )
    dialect_options = cast(
        "dict[str, object]",
        candidate_index.get("dialect_options", {}),
    )
    predicate = str(dialect_options.get("postgresql_where", "")).casefold()
    assert all(column_name in predicate for column_name in _SCORE_CANDIDATE_PREDICATE_COLUMNS)
    assert " and " in predicate
    assert " or " not in predicate

    assert _read_score_candidate_index_validity(connection) == (True, True)


def _read_score_candidate_index_oid(connection: Connection) -> int:
    pg_class = sa.table(
        "pg_class",
        sa.column("oid", sa.BigInteger()),
        sa.column("relname", sa.Text()),
        sa.column("relnamespace", sa.BigInteger()),
        schema="pg_catalog",
    )
    pg_namespace = sa.table(
        "pg_namespace",
        sa.column("oid", sa.BigInteger()),
        sa.column("nspname", sa.Text()),
        schema="pg_catalog",
    )
    statement = (
        sa.select(pg_class.c.oid)
        .select_from(
            pg_class.join(
                pg_namespace,
                pg_namespace.c.oid == pg_class.c.relnamespace,
            )
        )
        .where(
            pg_class.c.relname == _SCORE_CANDIDATE_INDEX,
            pg_namespace.c.nspname == sa.func.current_schema(),
        )
    )
    return cast("int", connection.execute(statement).scalar_one())


def _read_score_candidate_index_validity(connection: Connection) -> tuple[bool, bool] | None:
    pg_index = sa.table(
        "pg_index",
        sa.column("indexrelid", sa.BigInteger()),
        sa.column("indisvalid", sa.Boolean()),
        sa.column("indisready", sa.Boolean()),
        schema="pg_catalog",
    )
    pg_class = sa.table(
        "pg_class",
        sa.column("oid", sa.BigInteger()),
        sa.column("relname", sa.Text()),
        sa.column("relnamespace", sa.BigInteger()),
        schema="pg_catalog",
    )
    pg_namespace = sa.table(
        "pg_namespace",
        sa.column("oid", sa.BigInteger()),
        sa.column("nspname", sa.Text()),
        schema="pg_catalog",
    )
    statement = (
        sa.select(pg_index.c.indisvalid, pg_index.c.indisready)
        .select_from(
            pg_index.join(pg_class, pg_class.c.oid == pg_index.c.indexrelid).join(
                pg_namespace,
                pg_namespace.c.oid == pg_class.c.relnamespace,
            )
        )
        .where(
            pg_class.c.relname == _SCORE_CANDIDATE_INDEX,
            pg_namespace.c.nspname == sa.func.current_schema(),
        )
    )
    return cast(
        "tuple[bool, bool] | None",
        connection.execute(statement).tuples().one_or_none(),
    )


def _replace_projection_with_legacy_duplicate_rows(connection: Connection) -> None:
    operations = Operations(MigrationContext.configure(connection))
    operations.drop_table("beatmap_leaderboard_user_bests")
    mod_filter_key = sa.Column("mod_filter_key", sa.Integer(), nullable=True)
    _ = operations.create_table(
        "beatmap_leaderboard_user_bests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("beatmap_id", sa.Integer(), nullable=False),
        sa.Column("ruleset", sa.SmallInteger(), nullable=False),
        sa.Column("playstyle", sa.SmallInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        mod_filter_key,
        sa.Column("score_id", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            sa.or_(mod_filter_key.is_(None), mod_filter_key >= 0),
            name="ck_beatmap_leaderboard_user_bests_mod_filter_key_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["score_id"],
            ["scores.id"],
            name="fk_beatmap_leaderboard_user_bests_score_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    projection = sa.table(
        "beatmap_leaderboard_user_bests",
        sa.column("beatmap_id", sa.Integer()),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
        sa.column("mod_filter_key", sa.Integer()),
        sa.column("score_id", sa.BigInteger()),
        sa.column("score", sa.Integer()),
        sa.column("submitted_at", sa.DateTime(timezone=True)),
    )
    _ = connection.execute(
        sa.insert(projection),
        [
            {
                "beatmap_id": _BEATMAP_ID,
                "ruleset": Ruleset.OSU.value,
                "playstyle": Playstyle.VANILLA.value,
                "user_id": _USER_1_ID,
                "mod_filter_key": None,
                "score_id": _NO_MOD_SCORE_ID,
                "score": 1_000_000,
                "submitted_at": _NOW,
            },
            {
                "beatmap_id": _BEATMAP_ID,
                "ruleset": Ruleset.OSU.value,
                "playstyle": Playstyle.VANILLA.value,
                "user_id": _USER_1_ID,
                "mod_filter_key": 0,
                "score_id": _NO_MOD_SCORE_ID,
                "score": 1_000_000,
                "submitted_at": _NOW,
            },
        ],
    )


def _read_projection_schema(
    connection: Connection,
) -> tuple[frozenset[str], frozenset[str]]:
    inspector = sa.inspect(connection)
    columns = frozenset(
        str(column["name"]) for column in inspector.get_columns("beatmap_leaderboard_user_bests")
    )
    unique_constraints = frozenset(
        str(name)
        for constraint in inspector.get_unique_constraints("beatmap_leaderboard_user_bests")
        if (name := constraint["name"]) is not None
    )
    return columns, unique_constraints


def _read_mod_scoped_projection_schema(
    connection: Connection,
) -> tuple[
    frozenset[str],
    dict[str, tuple[str, ...]],
    frozenset[str],
    frozenset[str],
]:
    inspector = sa.inspect(connection)
    columns = frozenset(
        str(column["name"]) for column in inspector.get_columns("beatmap_leaderboard_user_bests")
    )
    unique_constraints = {
        str(name): tuple(str(column_name) for column_name in constraint["column_names"])
        for constraint in inspector.get_unique_constraints("beatmap_leaderboard_user_bests")
        if (name := constraint["name"]) is not None
    }
    check_constraints = frozenset(
        str(name)
        for constraint in inspector.get_check_constraints("beatmap_leaderboard_user_bests")
        if (name := constraint["name"]) is not None
    )
    indexes = frozenset(
        str(name)
        for index in inspector.get_indexes("beatmap_leaderboard_user_bests")
        if (name := index["name"]) is not None
    )
    return columns, unique_constraints, check_constraints, indexes


def _assert_checked_enum_storage(connection: Connection) -> None:
    inspector = sa.inspect(connection)
    for table_name, column_name, constraint_name, expected_length in _CHECKED_ENUM_COLUMNS:
        reflected_column = next(
            column for column in inspector.get_columns(table_name) if column["name"] == column_name
        )
        column_type = reflected_column["type"]
        assert isinstance(column_type, sa.String)
        assert not isinstance(column_type, ENUM)
        assert column_type.length == expected_length
        constraint_names = {
            str(name)
            for constraint in inspector.get_check_constraints(table_name)
            if (name := constraint["name"]) is not None
        }
        assert constraint_name in constraint_names


async def _seed_fixture(connection: AsyncConnection) -> None:
    await _delete_fixture(connection)
    _ = await connection.execute(
        sa.insert(RoleModel),
        [
            {
                "id": _ROLE_ID,
                "name": "enum_scope_pg_visible",
                "permissions": LEADERBOARD_VISIBLE_PERMISSION_MASK,
                "position": 0,
            }
        ],
    )
    _ = await connection.execute(
        sa.insert(UserModel),
        [
            {
                "id": _USER_1_ID,
                "username": "enum_pg_u1",
                "safe_username": "enum_pg_u1",
                "email": "enum-pg-u1@example.invalid",
                "password_hash": "test",
                "country": "JP",
            },
            {
                "id": _USER_2_ID,
                "username": "enum_pg_u2",
                "safe_username": "enum_pg_u2",
                "email": "enum-pg-u2@example.invalid",
                "password_hash": "test",
                "country": "US",
            },
        ],
    )
    _ = await connection.execute(
        sa.insert(UserRoleModel),
        [
            {"user_id": _USER_1_ID, "role_id": _ROLE_ID},
            {"user_id": _USER_2_ID, "role_id": _ROLE_ID},
        ],
    )
    _ = await connection.execute(
        sa.insert(BeatmapSetModel),
        [
            {
                "id": _BEATMAPSET_ID,
                "artist": "Migration Artist",
                "title": "Migration Title",
                "creator": "Migration Creator",
                "artist_unicode": None,
                "title_unicode": None,
                "official_status": BeatmapRankStatus.RANKED.value,
                "official_status_source": BeatmapMetadataSource.OFFICIAL.value,
                "official_status_verified": True,
            }
        ],
    )
    _ = await connection.execute(
        sa.insert(BeatmapModel),
        [
            {
                "id": _BEATMAP_ID,
                "beatmapset_id": _BEATMAPSET_ID,
                "checksum_md5": _CURRENT_CHECKSUM,
                "mode": BeatmapMode.OSU.value,
                "version": "Migration Difficulty",
                "official_status": BeatmapRankStatus.RANKED.value,
                "official_status_source": BeatmapMetadataSource.OFFICIAL.value,
                "official_status_verified": True,
                "local_status_override": None,
            }
        ],
    )
    _ = await connection.execute(sa.insert(ScoreModel), _score_rows())


async def _delete_fixture(connection: AsyncConnection) -> None:
    _ = await connection.execute(
        sa.delete(BeatmapLeaderboardUserBestModel).where(
            BeatmapLeaderboardUserBestModel.beatmap_id == _BEATMAP_ID
        )
    )
    _ = await connection.execute(sa.delete(ScoreModel).where(ScoreModel.id.in_(_SCORE_IDS)))
    _ = await connection.execute(
        sa.delete(UserRoleModel).where(UserRoleModel.user_id.in_((_USER_1_ID, _USER_2_ID)))
    )
    _ = await connection.execute(sa.delete(RoleModel).where(RoleModel.id == _ROLE_ID))
    _ = await connection.execute(
        sa.delete(UserModel).where(UserModel.id.in_((_USER_1_ID, _USER_2_ID)))
    )
    _ = await connection.execute(sa.delete(BeatmapModel).where(BeatmapModel.id == _BEATMAP_ID))
    _ = await connection.execute(
        sa.delete(BeatmapSetModel).where(BeatmapSetModel.id == _BEATMAPSET_ID)
    )


def _score_rows() -> list[dict[str, object]]:
    return [
        _score_values(
            score_id=_NO_MOD_SCORE_ID,
            user_id=_USER_1_ID,
            mods=int(Mod.NONE),
            score=1_000,
            submitted_at=_NOW,
        ),
        _score_values(
            score_id=_NIGHTCORE_SCORE_ID,
            user_id=_USER_1_ID,
            mods=int(Mod.NIGHTCORE | Mod.DOUBLE_TIME),
            score=900,
            submitted_at=_NOW + timedelta(seconds=1),
        ),
        _score_values(
            score_id=_DOUBLE_TIME_SCORE_ID,
            user_id=_USER_1_ID,
            mods=int(Mod.DOUBLE_TIME),
            score=950,
            submitted_at=_NOW + timedelta(seconds=2),
        ),
        _score_values(
            score_id=_PERFECT_SCORE_ID,
            user_id=_USER_1_ID,
            mods=int(Mod.PERFECT | Mod.SUDDEN_DEATH),
            score=800,
            submitted_at=_NOW + timedelta(seconds=3),
        ),
        _score_values(
            score_id=_SUDDEN_DEATH_SCORE_ID,
            user_id=_USER_1_ID,
            mods=int(Mod.SUDDEN_DEATH),
            score=850,
            submitted_at=_NOW + timedelta(seconds=4),
        ),
        _score_values(
            score_id=_USER_2_NIGHTCORE_SCORE_ID,
            user_id=_USER_2_ID,
            mods=int(Mod.NIGHTCORE | Mod.DOUBLE_TIME),
            score=1_100,
            submitted_at=_NOW + timedelta(seconds=5),
        ),
        _score_values(
            score_id=_STALE_SCORE_ID,
            user_id=_USER_1_ID,
            mods=int(Mod.NONE),
            score=9_999,
            submitted_at=_NOW + timedelta(seconds=6),
            beatmap_checksum=_STALE_CHECKSUM,
        ),
        _score_values(
            score_id=_DOUBLE_TIME_LOWER_SCORE_ID,
            user_id=_USER_1_ID,
            mods=int(Mod.DOUBLE_TIME),
            score=940,
            submitted_at=_NOW + timedelta(seconds=7),
        ),
        _score_values(
            score_id=_MIRROR_SCORE_ID,
            user_id=_USER_1_ID,
            mods=int(Mod.MIRROR),
            score=700,
            submitted_at=_NOW + timedelta(seconds=8),
        ),
    ]


def _score_values(
    *,
    score_id: int,
    user_id: int,
    mods: int,
    score: int,
    submitted_at: datetime,
    beatmap_checksum: str = _CURRENT_CHECKSUM,
) -> dict[str, object]:
    return {
        "id": score_id,
        "user_id": user_id,
        "beatmap_id": _BEATMAP_ID,
        "beatmap_checksum": beatmap_checksum,
        "online_checksum": f"{score_id:032x}",
        "ruleset": Ruleset.OSU.value,
        "playstyle": Playstyle.VANILLA.value,
        "mods": mods,
        "n300": 300,
        "n100": 10,
        "n50": 1,
        "geki": 0,
        "katu": 0,
        "miss": 0,
        "score": score,
        "max_combo": 500,
        "accuracy": 0.99,
        "grade": Grade.S.value,
        "passed": True,
        "perfect": False,
        "client_version": "migration-test",
        "submitted_at": submitted_at,
        "beatmap_status_at_submission": BeatmapRankStatus.RANKED.value,
        "leaderboard_eligible_at_submission": True,
        "replay_view_count": 0,
    }


def _read_scope(
    category: LeaderboardCategory,
    *,
    selected_mods: ModCombination | None = None,
) -> LeaderboardReadScope:
    return LeaderboardReadScope(
        beatmap_id=_BEATMAP_ID,
        beatmap_checksum=_CURRENT_CHECKSUM,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        category=category,
        selected_mods=selected_mods,
    )


def _projection_upsert(
    *,
    beatmap_checksum: str,
    score_id: int,
    score: int,
    submitted_at: datetime,
) -> UpsertBeatmapLeaderboardUserBest:
    return UpsertBeatmapLeaderboardUserBest(
        scope=BeatmapLeaderboardUserBestScope(
            beatmap_id=_BEATMAP_ID,
            beatmap_checksum=beatmap_checksum,
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
            user_id=_USER_1_ID,
            mods=ModCombination.none(),
        ),
        score_id=score_id,
        rank_key=ScoreRankKey(
            score=score,
            submitted_at=submitted_at,
            score_id=score_id,
        ),
    )


async def _legacy_projection_rows(
    connection: AsyncConnection,
) -> Sequence[tuple[int, int | None, int]]:
    projection = sa.table(
        "beatmap_leaderboard_user_bests",
        sa.column("beatmap_id", sa.Integer()),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
        sa.column("mod_filter_key", sa.Integer()),
        sa.column("score_id", sa.BigInteger()),
    )
    result = await connection.execute(
        sa.select(
            projection.c.user_id,
            projection.c.mod_filter_key,
            projection.c.score_id,
        ).where(
            projection.c.beatmap_id == _BEATMAP_ID,
            projection.c.ruleset == Ruleset.OSU.value,
            projection.c.playstyle == Playstyle.VANILLA.value,
        )
    )
    return cast("Sequence[tuple[int, int | None, int]]", result.tuples().all())


async def _replace_legacy_global_with_stale_score(
    connection: AsyncConnection,
) -> None:
    projection = sa.table(
        "beatmap_leaderboard_user_bests",
        sa.column("beatmap_id", sa.Integer()),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
        sa.column("mod_filter_key", sa.Integer()),
        sa.column("score_id", sa.BigInteger()),
        sa.column("score", sa.Integer()),
        sa.column("submitted_at", sa.DateTime(timezone=True)),
    )
    _ = await connection.execute(
        sa.update(projection)
        .where(
            projection.c.beatmap_id == _BEATMAP_ID,
            projection.c.ruleset == Ruleset.OSU.value,
            projection.c.playstyle == Playstyle.VANILLA.value,
            projection.c.user_id == _USER_1_ID,
            projection.c.mod_filter_key.is_(None),
        )
        .values(
            score_id=_STALE_SCORE_ID,
            score=9_999,
            submitted_at=_NOW + timedelta(seconds=6),
        )
    )


async def _global_projection_rows(
    connection: AsyncConnection,
) -> Sequence[tuple[int, str, int]]:
    projection = sa.table(
        "beatmap_leaderboard_user_bests",
        sa.column("beatmap_id", sa.Integer()),
        sa.column("user_id", sa.Integer()),
        sa.column("beatmap_checksum", sa.String(length=32)),
        sa.column("score_id", sa.BigInteger()),
    )
    result = await connection.execute(
        sa.select(
            projection.c.user_id,
            projection.c.beatmap_checksum,
            projection.c.score_id,
        ).where(projection.c.beatmap_id == _BEATMAP_ID)
    )
    return cast("Sequence[tuple[int, str, int]]", result.tuples().all())


async def _mod_scoped_projection_rows(
    connection: AsyncConnection,
) -> Sequence[tuple[int, str, int, int]]:
    projection = sa.table(
        "beatmap_leaderboard_user_bests",
        sa.column("beatmap_id", sa.Integer()),
        sa.column("user_id", sa.Integer()),
        sa.column("beatmap_checksum", sa.String(length=32)),
        sa.column("mods", sa.Integer()),
        sa.column("score_id", sa.BigInteger()),
    )
    result = await connection.execute(
        sa.select(
            projection.c.user_id,
            projection.c.beatmap_checksum,
            projection.c.mods,
            projection.c.score_id,
        ).where(projection.c.beatmap_id == _BEATMAP_ID)
    )
    return cast("Sequence[tuple[int, str, int, int]]", result.tuples().all())
