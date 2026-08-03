"""user latest activity metadataを追加するmigration.

Revision ID: 20260710_0300
Revises: 20260710_0200
Create Date: 2026-07-10 03:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260710_0300"
down_revision: str | None = "20260710_0200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Latest activity timestampをcreated_atでbackfillして必須columnへ移行する.

    Returns:
        None: usersのlatest_activity_at backfillとnon-null schema変更を完了したことを示す.

    Notes:
        text UPDATEは既存user rowの初期activity値をcreated_atから復元するために使用する.
    """
    op.add_column(
        "users",
        sa.Column(
            "latest_activity_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE users
            SET latest_activity_at = created_at
            WHERE latest_activity_at IS NULL
            """
        )
    )
    op.alter_column(
        "users",
        "latest_activity_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def downgrade() -> None:
    """User latest activity metadata columnを削除する.

    Returns:
        None: usersからlatest_activity_atを削除したことを示す.
    """
    op.drop_column("users", "latest_activity_at")
