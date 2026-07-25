"""User latest activity migrationのschemaとmetadata contractを検証する."""

from pathlib import Path
from typing import cast

from sqlalchemy import Column, DateTime, Table

from osu_server.repositories.sqlalchemy.models import UserModel

MIGRATION_PATH = Path("alembic/versions/20260710_0300_add_user_latest_activity.py")


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


def test_user_latest_activity_migration_adds_non_null_metadata_column() -> None:
    """Latest activity migrationがbackfill可能なnon-null columnを追加することを検証する.

    固定revisionのsourceを読み込み, created_atからのbackfill, defaultなしの追加, downgrade時の
    column削除というobservable contractを確認する.

    Returns:
        None: migration sourceのlatest activity schema contractを検証して完了する.
    """
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260710_0300"' in migration
    assert 'down_revision: str | None = "20260710_0200"' in migration
    assert '"latest_activity_at"' in migration
    assert "sa.DateTime(timezone=True)" in migration
    assert "UPDATE users" in migration
    assert "latest_activity_at = created_at" in migration
    add_column_section = migration.split("UPDATE users", maxsplit=1)[0]
    assert "server_default=sa.func.now()" not in add_column_section
    assert "updated_at" not in migration
    assert 'op.drop_column("users", "latest_activity_at")' in migration


def test_user_model_metadata_exposes_non_null_latest_activity() -> None:
    """UserModel metadataがnon-null latest activity timestampを公開することを検証する.

    現行model tableを条件に, timezone-aware DateTime, non-nullability, server defaultが
    observable metadataとして存在することを確認する.

    Returns:
        None: UserModelのlatest activity metadata contractを検証して完了する.
    """
    table = cast("Table", UserModel.__table__)

    latest_activity = _column(table, "latest_activity_at")
    assert isinstance(latest_activity.type, DateTime)
    assert latest_activity.type.timezone is True
    assert not latest_activity.nullable
    assert latest_activity.server_default is not None
