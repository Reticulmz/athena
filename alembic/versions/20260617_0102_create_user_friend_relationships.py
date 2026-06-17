"""Create user friend relationships table.

Revision ID: 20260617_0102
Revises: 20260617_0101
Create Date: 2026-06-17 16:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260617_0102"
down_revision: str | None = "20260617_0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_friend_relationships",
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "owner_user_id <> target_user_id",
            name="ck_user_friend_relationships_no_self",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_user_friend_relationships_owner_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_user_friend_relationships_target_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("owner_user_id", "target_user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_friend_relationships")
