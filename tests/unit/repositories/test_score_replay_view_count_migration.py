"""Score replay view count migrationのschemaとmetadata contractを検証する."""

from pathlib import Path
from typing import cast

from sqlalchemy import BigInteger, CheckConstraint, Column, Table

from osu_server.repositories.sqlalchemy.models import ScoreModel

MIGRATION_PATH = Path("alembic/versions/20260710_0200_add_score_replay_view_count.py")


def _column(table: Table, name: str) -> Column[object]:
    """Tableから指定名のcolumnをtyped Columnとして取得する.

    Args:
        table (Table): columnを所有するSQLAlchemy table metadata.
        name (str): 存在することを前提に取得するcolumn名.

    Returns:
        Column[object]: 指定名に対応するtyped column.

    Raises:
        KeyError: tableにnameのcolumnが存在しない場合.
    """
    return cast("Column[object]", table.c[name])


def _check_constraints(table: Table) -> set[str]:
    """Tableに定義されたCHECK constraint名を収集する.

    Args:
        table (Table): CHECK constraintを検証するSQLAlchemy table metadata.

    Returns:
        set[str]: tableに登録されたCHECK constraint名の集合.
    """
    return {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_score_replay_view_count_migration_adds_non_null_default_and_constraint() -> None:
    """Replay view count migrationが安全な初期値とnon-negative constraintを追加することを検証する.

    固定revisionのsourceを読み込み, zero defaultとbackfill, non-negative CHECK, downgrade時の
    column削除がobservable contractとして存在することを確認する.

    Returns:
        None: replay view count migration contractを検証して完了する.
    """
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260710_0200"' in migration
    assert 'down_revision: str | None = "20260710_0100"' in migration
    assert '"replay_view_count"' in migration
    assert "sa.BigInteger()" in migration
    assert 'server_default=sa.text("0")' in migration
    assert "UPDATE scores" in migration
    assert "replay_view_count = 0" in migration
    assert "ck_scores_replay_view_count_non_negative" in migration
    assert "replay_view_count >= 0" in migration
    assert 'op.drop_column("scores", "replay_view_count")' in migration


def test_score_model_metadata_exposes_non_null_non_negative_replay_view_count() -> None:
    """ScoreModel metadataがnon-null non-negative replay view countを公開することを検証する.

    現行score tableを条件に, BigInteger型, default, server default, CHECK constraintが
    observable metadataとして存在することを確認する.

    Returns:
        None: replay view count metadata contractを検証して完了する.
    """
    table = cast("Table", ScoreModel.__table__)

    replay_view_count = _column(table, "replay_view_count")
    assert isinstance(replay_view_count.type, BigInteger)
    assert not replay_view_count.nullable
    assert replay_view_count.default is not None
    assert replay_view_count.server_default is not None
    assert "ck_scores_replay_view_count_non_negative" in _check_constraints(table)
