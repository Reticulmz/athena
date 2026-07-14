"""leaderboard projectionをraw Mod scope単位へ再構築するmigration.

Revision ID: 20260713_0600
Revises: 20260712_0500
Create Date: 2026-07-13 06:00:00.000000
"""

from __future__ import annotations

from hashlib import blake2b
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260713_0600"
down_revision: str | None = "20260712_0500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECTION_TABLE = "beatmap_leaderboard_user_bests"
_MOD_SCOPED_PROJECTION_STAGING_TABLE = "_beatmap_leaderboard_user_bests_0600_mod_scoped"
_GLOBAL_PROJECTION_STAGING_TABLE = "_beatmap_leaderboard_user_bests_0600_global"
_SCOPE_UNIQUE_CONSTRAINT = "uq_beatmap_leaderboard_user_bests_scope"
_SCORE_UNIQUE_CONSTRAINT = "uq_beatmap_leaderboard_user_bests_score_id"
_MODS_CHECK_CONSTRAINT = "ck_beatmap_leaderboard_user_bests_mods_non_negative"
_SCORE_FOREIGN_KEY = "fk_beatmap_leaderboard_user_bests_score_id"
_USER_REBUILD_INDEX = "idx_beatmap_leaderboard_user_bests_user_rebuild"
_GLOBAL_SCOPE_UNIQUE_CONSTRAINT = "uq_beatmap_leaderboard_user_bests_global_scope_0400"
_GLOBAL_SCORE_UNIQUE_CONSTRAINT = "uq_beatmap_leaderboard_user_bests_global_score_id_0400"
_GLOBAL_SCORE_FOREIGN_KEY = "fk_beatmap_leaderboard_user_bests_global_score_id_0400"
_GLOBAL_USER_REBUILD_INDEX = "idx_beatmap_leaderboard_user_bests_global_user_rebuild_0400"
_PROJECTION_REBUILD_LOCK_NAMESPACE = "beatmap_leaderboard_user_bests:rebuild"


def upgrade() -> None:
    """projectionをraw Mod bitflagごとのuser bestへ移行する.

    Returns:
        None: staging tableのbackfillとatomic swapが完了したことを示す.
    """
    lock_projection_updates()
    _create_mod_scoped_projection_table(_MOD_SCOPED_PROJECTION_STAGING_TABLE)
    _rebuild_projection(
        _MOD_SCOPED_PROJECTION_STAGING_TABLE,
        partition_by_mods=True,
    )
    op.create_unique_constraint(
        _SCOPE_UNIQUE_CONSTRAINT,
        _MOD_SCOPED_PROJECTION_STAGING_TABLE,
        ["beatmap_id", "ruleset", "playstyle", "user_id", "mods"],
    )
    op.create_unique_constraint(
        _SCORE_UNIQUE_CONSTRAINT,
        _MOD_SCOPED_PROJECTION_STAGING_TABLE,
        ["score_id"],
    )
    op.create_index(
        _USER_REBUILD_INDEX,
        _MOD_SCOPED_PROJECTION_STAGING_TABLE,
        ["user_id", "beatmap_id", "ruleset", "playstyle"],
    )
    _replace_projection_table(_MOD_SCOPED_PROJECTION_STAGING_TABLE)


def downgrade() -> None:
    """projectionをGlobal all-modsのuser bestへ戻す.

    Returns:
        None: Global staging tableのbackfillとatomic swapが完了したことを示す.
    """
    lock_projection_updates()
    _create_global_projection_table(_GLOBAL_PROJECTION_STAGING_TABLE)
    _rebuild_projection(
        _GLOBAL_PROJECTION_STAGING_TABLE,
        partition_by_mods=False,
    )
    op.create_unique_constraint(
        _GLOBAL_SCOPE_UNIQUE_CONSTRAINT,
        _GLOBAL_PROJECTION_STAGING_TABLE,
        ["beatmap_id", "ruleset", "playstyle", "user_id"],
    )
    op.create_unique_constraint(
        _GLOBAL_SCORE_UNIQUE_CONSTRAINT,
        _GLOBAL_PROJECTION_STAGING_TABLE,
        ["score_id"],
    )
    op.create_index(
        _GLOBAL_USER_REBUILD_INDEX,
        _GLOBAL_PROJECTION_STAGING_TABLE,
        ["user_id", "beatmap_id", "ruleset", "playstyle"],
    )
    _replace_projection_table(_GLOBAL_PROJECTION_STAGING_TABLE)


def _create_mod_scoped_projection_table(table_name: str) -> None:
    """raw Mod別projection用の空staging tableを作成する.

    Args:
        table_name (str): live tableと競合しないstaging table名.

    Returns:
        None: final column/FK/CHECKを持つ空tableを作成したことを示す.
    """
    mods = sa.column("mods", sa.Integer())
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("beatmap_id", sa.Integer(), nullable=False),
        sa.Column("beatmap_checksum", sa.String(length=32), nullable=False),
        sa.Column("ruleset", sa.SmallInteger(), nullable=False),
        sa.Column("playstyle", sa.SmallInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mods", sa.Integer(), nullable=False),
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
        sa.CheckConstraint(mods >= 0, name=_MODS_CHECK_CONSTRAINT),
        sa.ForeignKeyConstraint(
            ["score_id"],
            ["scores.id"],
            name=_SCORE_FOREIGN_KEY,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_global_projection_table(table_name: str) -> None:
    """0400 transitional Global projection用の空staging tableを作成する.

    Args:
        table_name (str): live tableと競合しないstaging table名.

    Returns:
        None: Global column/FKを持つ空tableを作成したことを示す.
    """
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("beatmap_id", sa.Integer(), nullable=False),
        sa.Column("beatmap_checksum", sa.String(length=32), nullable=False),
        sa.Column("ruleset", sa.SmallInteger(), nullable=False),
        sa.Column("playstyle", sa.SmallInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["score_id"],
            ["scores.id"],
            name=_GLOBAL_SCORE_FOREIGN_KEY,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def _replace_projection_table(staging_table: str) -> None:
    """完成済みstaging tableをlive projection tableへ置き換える.

    Args:
        staging_table (str): backfillとconstraint/index作成が完了したtable名.

    Returns:
        None: live table名へのatomic swapが完了したことを示す.

    Notes:
        source scanとindex構築はdrop前に完了し, live table lockを最小化する.
    """
    op.drop_table(_PROJECTION_TABLE)
    op.rename_table(staging_table, _PROJECTION_TABLE)


def lock_projection_updates() -> None:
    """migration rebuildをruntime submitとtransaction内で直列化する.

    Returns:
        None: transaction終了までexclusive maintenance lockを保持したことを示す.

    Raises:
        SQLAlchemyError: PostgreSQL advisory lockを取得できない場合.

    Notes:
        Runtime repositoryとnamespaceおよびBlake2b変換契約を共有する.
    """
    statement = sa.select(sa.func.pg_advisory_xact_lock(_projection_rebuild_lock_key()))
    _ = op.get_bind().execute(statement)


def _projection_rebuild_lock_key() -> int:
    """projection maintenance用のsigned 64-bit advisory lock keyを返す.

    Returns:
        int: runtime submit/rebuildと共有するPostgreSQL advisory lock key.
    """
    return int.from_bytes(
        blake2b(_PROJECTION_REBUILD_LOCK_NAMESPACE.encode(), digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )


def _rebuild_projection(
    projection_table: str,
    *,
    partition_by_mods: bool,
) -> None:
    """source ScoresからGlobalまたはraw Mod別winnerをstaging tableへ保存する.

    Args:
        projection_table (str): backfill対象のstaging table名.
        partition_by_mods (bool): raw Mod bitmaskをwinner scopeへ含めるかどうか.

    Returns:
        None: current-checksum eligible winnerのbackfillが完了したことを示す.
    """
    projection = sa.table(
        projection_table,
        sa.column("beatmap_id", sa.Integer()),
        sa.column("beatmap_checksum", sa.String(length=32)),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
        sa.column("mods", sa.Integer()),
        sa.column("score_id", sa.BigInteger()),
        sa.column("score", sa.Integer()),
        sa.column("submitted_at", sa.DateTime(timezone=True)),
    )
    scores = sa.table(
        "scores",
        sa.column("id", sa.BigInteger()),
        sa.column("beatmap_id", sa.Integer()),
        sa.column("beatmap_checksum", sa.String(length=32)),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
        sa.column("mods", sa.Integer()),
        sa.column("score", sa.Integer()),
        sa.column("submitted_at", sa.DateTime(timezone=True)),
        sa.column("passed", sa.Boolean()),
        sa.column("leaderboard_eligible_at_submission", sa.Boolean()),
    )
    beatmaps = sa.table(
        "beatmaps",
        sa.column("id", sa.Integer()),
        sa.column("checksum_md5", sa.String(length=32)),
    )

    partition_columns = [
        scores.c.beatmap_id,
        scores.c.ruleset,
        scores.c.playstyle,
        scores.c.user_id,
    ]
    if partition_by_mods:
        partition_columns.append(scores.c.mods)

    ranked = (
        sa.select(
            scores.c.beatmap_id,
            scores.c.beatmap_checksum,
            scores.c.ruleset,
            scores.c.playstyle,
            scores.c.user_id,
            scores.c.mods,
            scores.c.id.label("score_id"),
            scores.c.score,
            scores.c.submitted_at,
            sa.func.row_number()
            .over(
                partition_by=tuple(partition_columns),
                order_by=(
                    scores.c.score.desc(),
                    scores.c.submitted_at.asc(),
                    scores.c.id.asc(),
                ),
            )
            .label("candidate_rank"),
        )
        .select_from(
            scores.join(
                beatmaps,
                sa.and_(
                    beatmaps.c.id == scores.c.beatmap_id,
                    beatmaps.c.checksum_md5 == scores.c.beatmap_checksum,
                ),
            )
        )
        .where(
            scores.c.passed.is_(True),
            scores.c.leaderboard_eligible_at_submission.is_(True),
        )
        .subquery("ranked_mod_scoped_leaderboard_projection")
    )
    if partition_by_mods:
        target_columns = (
            "beatmap_id",
            "beatmap_checksum",
            "ruleset",
            "playstyle",
            "user_id",
            "mods",
            "score_id",
            "score",
            "submitted_at",
        )
        source_rows = sa.select(
            ranked.c.beatmap_id,
            ranked.c.beatmap_checksum,
            ranked.c.ruleset,
            ranked.c.playstyle,
            ranked.c.user_id,
            ranked.c.mods,
            ranked.c.score_id,
            ranked.c.score,
            ranked.c.submitted_at,
        )
    else:
        target_columns = (
            "beatmap_id",
            "beatmap_checksum",
            "ruleset",
            "playstyle",
            "user_id",
            "score_id",
            "score",
            "submitted_at",
        )
        source_rows = sa.select(
            ranked.c.beatmap_id,
            ranked.c.beatmap_checksum,
            ranked.c.ruleset,
            ranked.c.playstyle,
            ranked.c.user_id,
            ranked.c.score_id,
            ranked.c.score,
            ranked.c.submitted_at,
        )
    op.execute(
        sa.insert(projection).from_select(
            target_columns,
            source_rows.where(ranked.c.candidate_rank == 1),
        )
    )
