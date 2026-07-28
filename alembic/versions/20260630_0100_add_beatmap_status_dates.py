"""beatmap status date metadataを追加するmigration.

Revision ID: 20260630_0100
Revises: 20260628_0200
Create Date: 2026-06-30 01:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260630_0100"
down_revision: str | None = "20260628_0200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Local overrideとofficial status更新時刻のmetadata columnを追加する.

    Returns:
        None: beatmapsへ2つのnullable timestamp columnを追加したことを示す.
    """
    op.add_column(
        "beatmaps",
        sa.Column("local_status_override_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "beatmaps",
        sa.Column("official_last_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Beatmap status date metadata columnを削除する.

    Returns:
        None: official update時刻とlocal override変更時刻を削除したことを示す.
    """
    op.drop_column("beatmaps", "official_last_updated_at")
    op.drop_column("beatmaps", "local_status_override_changed_at")
