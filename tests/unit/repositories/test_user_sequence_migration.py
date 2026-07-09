"""users.id sequence repair migration の構造を検証する."""

from pathlib import Path

MIGRATION_PATH = Path("alembic/versions/20260710_0100_sync_users_id_sequence.py")


def test_users_id_sequence_migration_syncs_with_existing_users() -> None:
    """BanchoBot seed 後の users_id_seq を既存最大 id に同期する."""
    migration = MIGRATION_PATH.read_text()
    empty_users_fallback = (
        "COALESCE(existing_users.max_id, {_BANCHO_BOT_RESERVED_USER_ID}),\n            true"
    )

    assert 'revision: str = "20260710_0100"' in migration
    assert 'down_revision: str | None = "20260630_0300"' in migration
    assert "_BANCHO_BOT_RESERVED_USER_ID = 1" in migration
    assert "pg_get_serial_sequence('users', 'id')" in migration
    assert "SELECT MAX(id) AS max_id FROM users" in migration
    assert empty_users_fallback in migration
    assert "existing_users.max_id IS NOT NULL" not in migration
    assert "COUNT(*)" not in migration
    assert "setval(" in migration
