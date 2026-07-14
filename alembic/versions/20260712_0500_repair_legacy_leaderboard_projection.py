"""旧leaderboard projectionをGlobal 1行構造へ修復するmigration.

Revision ID: 20260712_0500
Revises: 20260710_0400
Create Date: 2026-07-12 05:00:00.000000
"""

from __future__ import annotations

from hashlib import blake2b
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine.interfaces import ReflectedColumn
    from sqlalchemy.engine.reflection import Inspector

revision: str = "20260712_0500"
down_revision: str | None = "20260710_0400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECTION_TABLE = "beatmap_leaderboard_user_bests"
_SCORE_CANDIDATE_INDEX = "idx_scores_beatmap_leaderboard_candidates"
_USER_REBUILD_INDEX = "idx_beatmap_leaderboard_user_bests_global_user_rebuild_0400"
_SCOPE_UNIQUE_CONSTRAINT = "uq_beatmap_leaderboard_user_bests_global_scope_0400"
_SCORE_UNIQUE_CONSTRAINT = "uq_beatmap_leaderboard_user_bests_global_score_id_0400"
_SCORE_FOREIGN_KEY = "fk_beatmap_leaderboard_user_bests_global_score_id_0400"
_PROJECTION_REBUILD_LOCK_NAMESPACE = "beatmap_leaderboard_user_bests:rebuild"
_CANONICAL_COLUMN_TYPE_SQL = {
    "id": "BIGINT",
    "beatmap_id": "INTEGER",
    "beatmap_checksum": "VARCHAR(32)",
    "ruleset": "SMALLINT",
    "playstyle": "SMALLINT",
    "user_id": "INTEGER",
    "score_id": "BIGINT",
    "score": "INTEGER",
    "submitted_at": "TIMESTAMP WITH TIME ZONE",
    "created_at": "TIMESTAMP WITH TIME ZONE",
    "updated_at": "TIMESTAMP WITH TIME ZONE",
}
_CANONICAL_COLUMNS = frozenset(_CANONICAL_COLUMN_TYPE_SQL)
_CANONICAL_USER_REBUILD_INDEX_COLUMNS = (
    "user_id",
    "beatmap_id",
    "ruleset",
    "playstyle",
)
_COLUMNS_WITHOUT_DEFAULTS = _CANONICAL_COLUMNS - {"id", "created_at", "updated_at"}


def upgrade() -> None:
    """旧2行構造をGlobal all-mods projectionへ修復する.

    Returns:
        None: canonical schemaとGlobal winnerの再構築が完了したことを示す.

    Raises:
        SQLAlchemyError: candidate indexまたはprojectionの修復に失敗した場合.

    Notes:
        Score candidate indexは同名の誤定義またはINVALID indexも含めてconcurrent
        再作成する. 旧projectionだけをsource of truthであるscoresから再生成する.
    """
    inspector = sa.inspect(op.get_bind())
    projection_is_canonical = _projection_is_canonical(inspector)
    _recreate_score_candidate_index()
    if not projection_is_canonical:
        _recreate_global_projection(inspector)


def downgrade() -> None:
    """0400へ戻すためScore candidate indexをonline削除する.

    Returns:
        None: candidate indexを削除してdowngradeが完了したことを示す.

    Raises:
        SQLAlchemyError: candidate indexのconcurrent削除に失敗した場合.

    Notes:
        0500は適用済み0400の履歴ドリフトを修復するcompatibility migrationである.
        Projectionは壊れた旧構造へ戻さず, 0500が所有するindexだけを削除する.
    """
    with op.get_context().autocommit_block():
        _drop_score_candidate_index()


def _projection_is_canonical(inspector: Inspector) -> bool:
    """Projection tableが現行ORM契約と一致するか判定する.

    Args:
        inspector (Inspector): 現在のPostgreSQL schemaを参照するinspector.

    Returns:
        bool: PK, column型/default, constraints, indexがcanonicalならTrue.
    """
    if not inspector.has_table(_PROJECTION_TABLE):
        return False

    columns = {str(column["name"]): column for column in inspector.get_columns(_PROJECTION_TABLE)}
    columns_are_canonical = (
        columns.keys() == _CANONICAL_COLUMNS
        and not any(bool(column["nullable"]) for column in columns.values())
        and all(
            column["type"].compile(dialect=inspector.bind.dialect) == expected_type
            for name, expected_type in _CANONICAL_COLUMN_TYPE_SQL.items()
            if (column := columns.get(name)) is not None
        )
        and _column_defaults_are_canonical(columns)
    )

    primary_key = inspector.get_pk_constraint(_PROJECTION_TABLE)
    primary_key_is_canonical = tuple(primary_key["constrained_columns"]) == ("id",)

    unique_constraints = {
        str(constraint["name"]): tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(_PROJECTION_TABLE)
        if constraint["name"] is not None
    }
    unique_constraints_are_canonical = unique_constraints == {
        _SCOPE_UNIQUE_CONSTRAINT: (
            "beatmap_id",
            "ruleset",
            "playstyle",
            "user_id",
        ),
        _SCORE_UNIQUE_CONSTRAINT: ("score_id",),
    }

    foreign_keys = {
        str(foreign_key["name"]): foreign_key
        for foreign_key in inspector.get_foreign_keys(_PROJECTION_TABLE)
        if foreign_key["name"] is not None
    }
    score_foreign_key = foreign_keys.get(_SCORE_FOREIGN_KEY)
    foreign_key_is_canonical = set(foreign_keys) == {_SCORE_FOREIGN_KEY} and (
        score_foreign_key is not None
        and tuple(score_foreign_key["constrained_columns"]) == ("score_id",)
        and score_foreign_key["referred_table"] == "scores"
        and tuple(score_foreign_key["referred_columns"]) == ("id",)
    )

    indexes = {
        str(index["name"]): index
        for index in inspector.get_indexes(_PROJECTION_TABLE)
        if index["name"] is not None
    }
    user_rebuild_index = indexes.get(_USER_REBUILD_INDEX)
    user_rebuild_index_is_canonical = user_rebuild_index is not None and (
        tuple(user_rebuild_index["column_names"]) == _CANONICAL_USER_REBUILD_INDEX_COLUMNS
        and not bool(user_rebuild_index["unique"])
    )
    return all(
        (
            columns_are_canonical,
            primary_key_is_canonical,
            unique_constraints_are_canonical,
            foreign_key_is_canonical,
            user_rebuild_index_is_canonical,
        )
    )


def _column_defaults_are_canonical(columns: dict[str, ReflectedColumn]) -> bool:
    id_column = columns.get("id")
    created_at_column = columns.get("created_at")
    updated_at_column = columns.get("updated_at")
    if id_column is None or created_at_column is None or updated_at_column is None:
        return False

    id_is_generated = id_column.get("identity") is not None or _is_nextval_default(id_column)
    timestamps_have_defaults = _is_current_timestamp_default(
        created_at_column
    ) and _is_current_timestamp_default(updated_at_column)
    other_columns_have_no_defaults = all(
        columns[name].get("default") is None and columns[name].get("identity") is None
        for name in _COLUMNS_WITHOUT_DEFAULTS
    )
    return id_is_generated and timestamps_have_defaults and other_columns_have_no_defaults


def _is_nextval_default(column: ReflectedColumn) -> bool:
    normalized = _normalized_default(column)
    return normalized is not None and normalized.startswith("nextval(")


def _is_current_timestamp_default(column: ReflectedColumn) -> bool:
    normalized = _normalized_default(column)
    return normalized in {"now()", "(now())", "current_timestamp", "(current_timestamp)"}


def _normalized_default(column: ReflectedColumn) -> str | None:
    default = column.get("default")
    if default is None:
        return None
    return "".join(str(default).casefold().split())


def _recreate_global_projection(inspector: Inspector) -> None:
    """旧projectionをcanonical tableへ置き換えてGlobal winnerを再生成する.

    Args:
        inspector (Inspector): 置換前schemaを参照するinspector.

    Returns:
        None: canonical tableとGlobal winnerが作成されたことを示す.

    Notes:
        Projectionはderived dataであり, 旧行は保持せずscoresから再導出する.
    """
    lock_projection_updates()
    if inspector.has_table(_PROJECTION_TABLE):
        op.drop_table(_PROJECTION_TABLE)

    op.create_table(
        _PROJECTION_TABLE,
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
            name=_SCORE_FOREIGN_KEY,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "beatmap_id",
            "ruleset",
            "playstyle",
            "user_id",
            name=_SCOPE_UNIQUE_CONSTRAINT,
        ),
        sa.UniqueConstraint("score_id", name=_SCORE_UNIQUE_CONSTRAINT),
    )
    op.create_index(
        _USER_REBUILD_INDEX,
        _PROJECTION_TABLE,
        ["user_id", "beatmap_id", "ruleset", "playstyle"],
    )
    _rebuild_current_global_projection()


def lock_projection_updates() -> None:
    """fallback repairをruntime submitとtransaction内で直列化する.

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


def _rebuild_current_global_projection() -> None:
    """Current checksumのscoresからユーザーごとのGlobal winnerを保存する.

    Returns:
        None: 各Beatmap/ruleset/playstyle/userの最高scoreを保存したことを示す.

    Notes:
        Passedかつsubmission時にleaderboard eligibleだったscoreだけを対象にする.
        同点はsubmitted_at昇順, score_id昇順で決定する.
    """
    projection = sa.table(
        _PROJECTION_TABLE,
        sa.column("beatmap_id", sa.Integer()),
        sa.column("beatmap_checksum", sa.String(length=32)),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
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
    ranked = (
        sa.select(
            scores.c.beatmap_id,
            scores.c.beatmap_checksum,
            scores.c.ruleset,
            scores.c.playstyle,
            scores.c.user_id,
            scores.c.id.label("score_id"),
            scores.c.score,
            scores.c.submitted_at,
            sa.func.row_number()
            .over(
                partition_by=(
                    scores.c.beatmap_id,
                    scores.c.ruleset,
                    scores.c.playstyle,
                    scores.c.user_id,
                ),
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
        .subquery("ranked_current_global_projection_repair")
    )
    op.execute(
        sa.insert(projection).from_select(
            (
                "beatmap_id",
                "beatmap_checksum",
                "ruleset",
                "playstyle",
                "user_id",
                "score_id",
                "score",
                "submitted_at",
            ),
            sa.select(
                ranked.c.beatmap_id,
                ranked.c.beatmap_checksum,
                ranked.c.ruleset,
                ranked.c.playstyle,
                ranked.c.user_id,
                ranked.c.score_id,
                ranked.c.score,
                ranked.c.submitted_at,
            ).where(ranked.c.candidate_rank == 1),
        )
    )


def _recreate_score_candidate_index() -> None:
    """Selected Mods read-time query用のscore indexをonline再作成する.

    Returns:
        None: canonicalなcandidate indexが存在することを示す.

    Raises:
        SQLAlchemyError: indexのconcurrent削除または作成に失敗した場合.

    Notes:
        PostgreSQLへの書き込みを継続できるようにtransaction外で実行する.
        名前だけでは誤定義やINVALID状態を識別できないため, 同名indexを必ず
        concurrent dropしてから再作成する.
    """
    with op.get_context().autocommit_block():
        _drop_score_candidate_index()
        op.create_index(
            _SCORE_CANDIDATE_INDEX,
            "scores",
            [
                "beatmap_id",
                "ruleset",
                "playstyle",
                "beatmap_checksum",
                "user_id",
                sa.column("score", sa.Integer()).desc(),
                sa.column("submitted_at", sa.DateTime(timezone=True)).asc(),
                sa.column("id", sa.BigInteger()).asc(),
            ],
            postgresql_where=sa.and_(
                sa.column("passed", sa.Boolean()).is_(True),
                sa.column("leaderboard_eligible_at_submission", sa.Boolean()).is_(True),
            ),
            postgresql_concurrently=True,
        )


def _drop_score_candidate_index() -> None:
    op.drop_index(
        _SCORE_CANDIDATE_INDEX,
        table_name="scores",
        if_exists=True,
        postgresql_concurrently=True,
    )
