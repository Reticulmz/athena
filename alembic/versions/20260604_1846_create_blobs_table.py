"""create blobs table

Revision ID: 20260604_1846
Revises: 20260525_2100
Create Date: 2026-06-04 18:46:00+09:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260604_1846"
down_revision: str | None = "20260525_2100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "blobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger, nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("storage_backend", sa.String(32), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("sha256", name="uq_blobs_sha256"),
        sa.CheckConstraint("byte_size >= 0", name="ck_blobs_byte_size_non_negative"),
    )


def downgrade() -> None:
    op.drop_table("blobs")
