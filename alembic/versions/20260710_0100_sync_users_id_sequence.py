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
    """users.id sequence を既存最大 id と同期する."""
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('users', 'id'),
            COALESCE((SELECT MAX(id) FROM users), 1),
            (SELECT COUNT(*) > 0 FROM users)
        )
        """
    )


def downgrade() -> None:
    """Sequence 同期は data repair のため downgrade では戻さない."""
