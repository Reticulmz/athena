"""sync users id sequence

Revision ID: 20260710_0100
Revises: 20260630_0300
Create Date: 2026-07-10 00:00:00+09:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260710_0100"
down_revision: str | None = "20260630_0300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """users.id sequence を既存最大 id と同期する.

    Returns:
        None: Alembic migration として永続的な schema/data repair を行う.

    Raises:
        Exception: SQL 実行時に Alembic/SQLAlchemy 由来の例外が送出される可能性がある.

    Notes:
        PostgreSQL の pg_get_serial_sequence と setval に依存する.
    """
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('users', 'id'),
            COALESCE(existing_users.max_id, 1),
            existing_users.max_id IS NOT NULL
        )
        FROM (SELECT MAX(id) AS max_id FROM users) AS existing_users
        """
    )


def downgrade() -> None:
    """Sequence 同期は data repair のため downgrade では戻さない."""
