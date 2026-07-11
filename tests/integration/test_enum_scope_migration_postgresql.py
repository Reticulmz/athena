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
from osu_server.domain.scores.mods import Mod
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
_REVISION = "20260710_0400"
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
_BLOB_ID = 1_970_200_001
_ATTACHMENT_ID = 9_700_100_001
_OLD_CALCULATION_ID = 9_700_200_001
_REPLACEMENT_CALCULATION_ID = 9_700_200_002
_SCORE_IDS = (
    _NO_MOD_SCORE_ID,
    _NIGHTCORE_SCORE_ID,
    _DOUBLE_TIME_SCORE_ID,
    _PERFECT_SCORE_ID,
    _SUDDEN_DEATH_SCORE_ID,
    _USER_2_NIGHTCORE_SCORE_ID,
    _STALE_SCORE_ID,
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
    """Migration test専用schemaへ接続するtransactional connectionを提供する.

    Args:
        postgres_engine (AsyncEngine): 実PostgreSQLへ接続するtest engine.

    Yields:
        AsyncConnection: head migration適用済みの専用schema接続.

    Notes:
        fixture終了時にtransactionをrollbackして専用schemaを破棄する.
    """
    async with postgres_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            schema_name = f"athena_enum_scope_{secrets.token_hex(8)}"
            _ = await connection.execute(sa.schema.CreateSchema(schema_name))
            _ = await connection.execute(
                sa.select(sa.func.set_config("search_path", schema_name, True))
            )
            await connection.run_sync(_upgrade_schema_to_head)
            yield connection
        finally:
            if transaction.is_active:
                await transaction.rollback()


async def test_postgresql_selected_mod_predicates_and_window_ranking(
    postgres_connection: AsyncConnection,
) -> None:
    """read-time Mod predicateとscore正本のwindow rankingを確認する.

    Args:
        postgres_connection (AsyncConnection): 専用schemaへ接続した非同期接続.

    Returns:
        None: GlobalとSelected Modsのrankingが期待値と一致したことを示す.

    Raises:
        AssertionError: filter, ranking, またはprojection更新結果が異なる場合.

    Notes:
        GlobalはMod条件なし, Selected Modsだけsource Scoreのmodsで絞り込む.
    """
    await _seed_fixture(postgres_connection)

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
            mod_filter_key=int(Mod.DOUBLE_TIME),
        ),
        limit=50,
    )
    sudden_death_rows = await query_repository.list_top_rows(
        _read_scope(
            LeaderboardCategory.SELECTED_MODS,
            mod_filter_key=int(Mod.SUDDEN_DEATH),
        ),
        limit=50,
    )
    no_mod_rows = await query_repository.list_top_rows(
        _read_scope(LeaderboardCategory.SELECTED_MODS, mod_filter_key=0),
        limit=50,
    )

    assert [(row.score_id, row.rank) for row in global_rows] == [
        (_USER_2_NIGHTCORE_SCORE_ID, 1),
        (_NO_MOD_SCORE_ID, 2),
    ]
    assert [row.score_id for row in double_time_rows] == [
        _USER_2_NIGHTCORE_SCORE_ID,
        _DOUBLE_TIME_SCORE_ID,
    ]
    assert [row.score_id for row in sudden_death_rows] == [_SUDDEN_DEATH_SCORE_ID]
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
    postgres_connection: AsyncConnection,
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
    await _seed_fixture(postgres_connection)

    await postgres_connection.run_sync(_run_downgrade)

    assert set(await _legacy_projection_rows(postgres_connection)) == {
        (_USER_1_ID, None, _NO_MOD_SCORE_ID),
        (_USER_1_ID, 0, _NO_MOD_SCORE_ID),
        (_USER_1_ID, int(Mod.SUDDEN_DEATH), _SUDDEN_DEATH_SCORE_ID),
        (_USER_1_ID, int(Mod.DOUBLE_TIME), _DOUBLE_TIME_SCORE_ID),
        (_USER_2_ID, None, _USER_2_NIGHTCORE_SCORE_ID),
        (_USER_2_ID, int(Mod.DOUBLE_TIME), _USER_2_NIGHTCORE_SCORE_ID),
    }

    await _replace_legacy_global_with_stale_score(postgres_connection)
    await postgres_connection.run_sync(_run_upgrade)

    assert set(await _current_projection_rows(postgres_connection)) == {
        (_USER_1_ID, _CURRENT_CHECKSUM, _NO_MOD_SCORE_ID),
        (_USER_2_ID, _CURRENT_CHECKSUM, _USER_2_NIGHTCORE_SCORE_ID),
    }


def _upgrade_schema_to_head(connection: Connection) -> None:
    operations = Operations(MigrationContext.configure(connection))
    script_directory = ScriptDirectory.from_config(Config("alembic.ini"))
    revisions = tuple(script_directory.walk_revisions(base="base", head=_REVISION))
    for revision in reversed(revisions):
        migration = cast("_MigrationModule", cast("object", revision.module))
        migration.op = operations
        migration.upgrade()


def _run_downgrade(connection: Connection) -> None:
    _MIGRATION.op = Operations(MigrationContext.configure(connection))
    _MIGRATION.downgrade()


def _run_upgrade(connection: Connection) -> None:
    _MIGRATION.op = Operations(MigrationContext.configure(connection))
    _MIGRATION.upgrade()


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
            mods=int(Mod.NIGHTCORE),
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
            mods=int(Mod.PERFECT),
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
            mods=int(Mod.NIGHTCORE),
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
    mod_filter_key: int | None = None,
) -> LeaderboardReadScope:
    return LeaderboardReadScope(
        beatmap_id=_BEATMAP_ID,
        beatmap_checksum=_CURRENT_CHECKSUM,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        category=category,
        mod_filter_key=mod_filter_key,
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


async def _current_projection_rows(
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
