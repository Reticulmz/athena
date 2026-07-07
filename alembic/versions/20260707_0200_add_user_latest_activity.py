"""Add user latest activity metadata.

Revision ID: 20260707_0200
Revises: 20260707_0100
Create Date: 2026-07-07 02:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260707_0200"
down_revision: str | None = "20260707_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    op.drop_column("users", "latest_activity_at")
