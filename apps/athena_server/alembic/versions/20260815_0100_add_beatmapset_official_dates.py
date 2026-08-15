"""beatmapset official date metadataを追加するmigration.

Revision ID: 20260815_0100
Revises: 20260809_0100
Create Date: 2026-08-15 01:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260815_0100"
down_revision: str | None = "20260809_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEATMAPSET_TABLE = "beatmapsets"


def upgrade() -> None:
    """Beatmapset単位の公式日時metadata columnを追加する.

    Returns:
        None: submitted,ranked,last updatedのnullable timestamp columnを追加したことを示す.
    """
    op.add_column(
        _BEATMAPSET_TABLE,
        sa.Column("official_submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        _BEATMAPSET_TABLE,
        sa.Column("official_ranked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        _BEATMAPSET_TABLE,
        sa.Column("official_last_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Beatmapset単位の公式日時metadata columnを削除する.

    Returns:
        None: submitted,ranked,last updated columnを削除したことを示す.
    """
    op.drop_column(_BEATMAPSET_TABLE, "official_last_updated_at")
    op.drop_column(_BEATMAPSET_TABLE, "official_ranked_at")
    op.drop_column(_BEATMAPSET_TABLE, "official_submitted_at")
