"""users.id sequenceを既存userと同期するmigration.

Revision ID: 20260710_0100
Revises: 20260630_0300
Create Date: 2026-07-10 00:00:00+09:00
"""

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260710_0100"
down_revision: str | None = "20260630_0300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BANCHO_BOT_RESERVED_USER_ID = 1


def upgrade() -> None:
    """users.id sequenceを既存最大IDまたはBanchoBot予約IDと同期する.

    Returns:
        None: 永続的なsequence repairを完了したことを示す.

    Raises:
        SQLAlchemyError: PostgreSQL sequence更新に失敗した場合.

    Notes:
        PostgreSQLのpg_get_serial_sequenceとsetvalに依存する.
        text SQLはsequence名の解決とMAX値のfallbackをdatabase内で原子的に実行するために使用する.
        `setval(..., 1, true)`は次のnextval()を2にするため, usersが空でもBanchoBot予約IDの1を
        再割り当てしない.
    """
    op.execute(
        f"""
        SELECT setval(
            pg_get_serial_sequence('users', 'id'),
            COALESCE(existing_users.max_id, {_BANCHO_BOT_RESERVED_USER_ID}),
            true
        )
        FROM (SELECT MAX(id) AS max_id FROM users) AS existing_users
        """
    )


def downgrade() -> None:
    """Sequence repairをrollbackせず意図的なno-opとして完了する.

    Returns:
        None: users.id sequenceを変更せずdowngradeを完了したことを示す.

    Notes:
        sequence repairは既存dataに対する前方修復であり, 安全に以前のcounter値を復元できない.
    """
