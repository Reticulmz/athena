"""Add personal best projection table.

Revision ID: 20260617_0101
Revises: 20260616_0100
Create Date: 2026-06-17 12:20:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260617_0101"
down_revision: str | None = "20260616_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personal_bests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("beatmap_id", sa.Integer(), nullable=False),
        sa.Column("ruleset", sa.SmallInteger(), nullable=False),
        sa.Column("playstyle", sa.SmallInteger(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("score_id", sa.BigInteger(), nullable=False),
        sa.Column("ranking_value", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["score_id"],
            ["scores.id"],
            name="fk_personal_bests_score_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_personal_bests_scope_unique",
        "personal_bests",
        ["user_id", "beatmap_id", "ruleset", "playstyle", "category"],
        unique=True,
    )
    op.create_index("idx_personal_bests_score_id", "personal_bests", ["score_id"])
    op.create_index(
        "idx_personal_bests_beatmap_category",
        "personal_bests",
        ["beatmap_id", "category"],
    )


def downgrade() -> None:
    op.drop_index("idx_personal_bests_beatmap_category", table_name="personal_bests")
    op.drop_index("idx_personal_bests_score_id", table_name="personal_bests")
    op.drop_index("idx_personal_bests_scope_unique", table_name="personal_bests")
    op.drop_table("personal_bests")
