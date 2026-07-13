"""Leaderboard read indexをonline作成するmigration.

Revision ID: 20260713_0700
Revises: 20260713_0600
Create Date: 2026-07-13 07:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260713_0700"
down_revision: str | None = "20260713_0600"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECTION_TABLE = "beatmap_leaderboard_user_bests"
_SCORE_TABLE = "scores"
_SCORE_CANDIDATE_INDEX = "idx_scores_beatmap_leaderboard_candidates"
_GLOBAL_RANK_INDEX = "idx_beatmap_leaderboard_user_bests_global_rank"
_MOD_RANK_INDEX = "idx_beatmap_leaderboard_user_bests_mod_rank"
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


def upgrade() -> None:
    """Leaderboard read indexをwrite-blockなしで検証および作成する.

    Returns:
        None: Score candidate, Global, Selected Mods用indexの準備完了を示す.

    Raises:
        SQLAlchemyError: index定義の検査, concurrent削除, または作成に失敗した場合.

    Notes:
        0600のschema/data移行を先に確定させた後, autocommit block内で
        `CREATE INDEX CONCURRENTLY`を実行する. Score candidate indexは誤定義または
        INVALIDの場合だけ置換し, rank indexは再実行可能な形で再作成する.
    """
    with op.get_context().autocommit_block():
        _repair_score_candidate_index()
        _drop_rank_indexes()
        _create_rank_indexes()


def downgrade() -> None:
    """Leaderboard read indexをwrite-blockなしで削除する.

    Returns:
        None: GlobalとSelected Mods用indexの削除が完了したことを示す.

    Raises:
        SQLAlchemyError: rank indexのconcurrent削除に失敗した場合.
    """
    with op.get_context().autocommit_block():
        _drop_rank_indexes()


def _repair_score_candidate_index() -> None:
    if _score_candidate_index_is_current():
        return

    op.drop_index(
        _SCORE_CANDIDATE_INDEX,
        table_name=_SCORE_TABLE,
        if_exists=True,
        postgresql_concurrently=True,
    )
    op.create_index(
        _SCORE_CANDIDATE_INDEX,
        _SCORE_TABLE,
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


def _score_candidate_index_is_current() -> bool:
    inspector = sa.inspect(op.get_bind())
    candidate_index = next(
        (
            index
            for index in inspector.get_indexes(_SCORE_TABLE)
            if index["name"] == _SCORE_CANDIDATE_INDEX
        ),
        None,
    )
    if candidate_index is None:
        return False

    column_names = tuple(str(name) for name in candidate_index["column_names"])
    column_sorting = {
        str(name): tuple(str(option).casefold() for option in options)
        for name, options in candidate_index.get("column_sorting", {}).items()
    }
    dialect_options = candidate_index.get("dialect_options", {})
    definition_is_current = all(
        (
            candidate_index["unique"] is False,
            column_names == _SCORE_CANDIDATE_COLUMNS,
            _score_candidate_sorting_is_compatible(column_sorting),
            _score_candidate_predicate_columns(dialect_options.get("postgresql_where", ""))
            == _SCORE_CANDIDATE_PREDICATE_COLUMNS,
        )
    )
    return definition_is_current and _score_candidate_index_is_valid()


def _score_candidate_index_is_valid() -> bool:
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
    state = op.get_bind().execute(statement).one_or_none()
    return state is not None and state.indisvalid is True and state.indisready is True


def _score_candidate_sorting_is_compatible(
    column_sorting: dict[str, tuple[str, ...]],
) -> bool:
    score_options = frozenset(column_sorting.get("score", ()))
    if "desc" not in score_options or "asc" in score_options:
        return False

    # Index keys are NOT NULL, so NULLS FIRST/LAST does not change their ordering contract.
    return all(
        "desc" not in options
        for column_name, options in column_sorting.items()
        if column_name != "score"
    )


def _score_candidate_predicate_columns(expression: object) -> frozenset[str] | None:
    normalized = " ".join(str(expression).casefold().replace('"', "").split())
    normalized = normalized.replace("(", "").replace(")", "")
    normalized = normalized.replace(f"{_SCORE_TABLE}.", "")
    terms = normalized.split(" and ")
    if len(terms) != len(_SCORE_CANDIDATE_PREDICATE_COLUMNS):
        return None

    columns: set[str] = set()
    for term in terms:
        column_name = _true_boolean_predicate_column(term)
        if column_name is None:
            return None
        columns.add(column_name)
    return frozenset(columns)


def _true_boolean_predicate_column(term: str) -> str | None:
    compact = term.replace(" ", "").replace("::boolean", "")
    for column_name in _SCORE_CANDIDATE_PREDICATE_COLUMNS:
        if compact in {
            column_name,
            f"{column_name}istrue",
            f"{column_name}=true",
            f"true={column_name}",
            f"{column_name}isnotfalse",
            f"{column_name}<>false",
            f"{column_name}!=false",
        }:
            return column_name
    return None


def _drop_rank_indexes() -> None:
    op.drop_index(
        _MOD_RANK_INDEX,
        table_name=_PROJECTION_TABLE,
        if_exists=True,
        postgresql_concurrently=True,
    )
    op.drop_index(
        _GLOBAL_RANK_INDEX,
        table_name=_PROJECTION_TABLE,
        if_exists=True,
        postgresql_concurrently=True,
    )


def _create_rank_indexes() -> None:
    op.create_index(
        _GLOBAL_RANK_INDEX,
        _PROJECTION_TABLE,
        [
            "beatmap_id",
            "ruleset",
            "playstyle",
            "beatmap_checksum",
            "user_id",
            sa.column("score", sa.Integer()).desc(),
            sa.column("submitted_at", sa.DateTime(timezone=True)).asc(),
            sa.column("score_id", sa.BigInteger()).asc(),
        ],
        postgresql_concurrently=True,
    )
    op.create_index(
        _MOD_RANK_INDEX,
        _PROJECTION_TABLE,
        [
            "beatmap_id",
            "ruleset",
            "playstyle",
            "beatmap_checksum",
            "mods",
            "user_id",
            sa.column("score", sa.Integer()).desc(),
            sa.column("submitted_at", sa.DateTime(timezone=True)).asc(),
            sa.column("score_id", sa.BigInteger()).asc(),
        ],
        postgresql_concurrently=True,
    )
