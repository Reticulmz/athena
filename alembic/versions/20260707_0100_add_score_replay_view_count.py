"""Add score replay view count.

Revision ID: 20260707_0100
Revises: 20260710_0100
Create Date: 2026-07-07 01:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260707_0100"
down_revision: str | None = "20260710_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scores",
        sa.Column(
            "replay_view_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE scores
            SET replay_view_count = 0
            WHERE replay_view_count IS NULL
            """
        )
    )
    op.alter_column(
        "scores",
        "replay_view_count",
        existing_type=sa.BigInteger(),
        nullable=False,
        server_default=sa.text("0"),
    )
    op.create_check_constraint(
        "ck_scores_replay_view_count_non_negative",
        "scores",
        "replay_view_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_scores_replay_view_count_non_negative",
        "scores",
        type_="check",
    )
    op.drop_column("scores", "replay_view_count")
