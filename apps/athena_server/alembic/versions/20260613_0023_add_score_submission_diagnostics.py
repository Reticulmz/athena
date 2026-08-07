"""score submission diagnostic fieldを追加するmigration.

Revision ID: 20260613_0023
Revises: 20260612_0022
Create Date: 2026-06-13 09:30:00.000000

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260613_0023"
down_revision: str | None = "20260612_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """submission時のbeatmap statusを保存するnullable columnを追加する.

    Returns:
        None: scoresへのbeatmap_status_at_submission追加を完了し, 呼び出し側へ値を返さずに
            終了する.
    """
    op.add_column(
        "scores",
        sa.Column("beatmap_status_at_submission", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    """submission時のbeatmap status columnを削除する.

    Returns:
        None: scoresからのbeatmap_status_at_submission削除を完了し, 呼び出し側へ値を返さずに
            終了する.
    """
    op.drop_column("scores", "beatmap_status_at_submission")
