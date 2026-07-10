from pathlib import Path
from typing import cast

from sqlalchemy import Column, DateTime, Table

from osu_server.repositories.sqlalchemy.models import UserModel

MIGRATION_PATH = Path("alembic/versions/20260710_0300_add_user_latest_activity.py")


def _column(table: Table, name: str) -> Column[object]:
    return cast("Column[object]", table.c[name])


def test_user_latest_activity_migration_adds_non_null_metadata_column() -> None:
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
    table = cast("Table", UserModel.__table__)

    latest_activity = _column(table, "latest_activity_at")
    assert isinstance(latest_activity.type, DateTime)
    assert latest_activity.type.timezone is True
    assert not latest_activity.nullable
    assert latest_activity.server_default is not None
