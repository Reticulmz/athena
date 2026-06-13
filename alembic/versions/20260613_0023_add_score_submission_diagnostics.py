"""Add score submission diagnostic fields.

Revision ID: 20260613_0023
Revises: 20260612_0022
Create Date: 2026-06-13 09:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260613_0023"
down_revision: str | None = "20260612_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scores",
        sa.Column("beatmap_status_at_submission", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scores", "beatmap_status_at_submission")
