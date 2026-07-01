"""Add score submit timing fields.

Revision ID: 20260628_0100
Revises: 20260618_0100
Create Date: 2026-06-28 01:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260628_0100"
down_revision: str | None = "20260618_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLAY_TIME_SOURCE_VALUES = ("'fail_time'", "'beatmap_total_length'")
_PLAY_TIME_SOURCE_CHECK = "play_time_source IS NULL OR play_time_source IN ({})".format(
    ", ".join(_PLAY_TIME_SOURCE_VALUES)
)


def upgrade() -> None:
    op.add_column("scores", sa.Column("fail_time_ms", sa.Integer(), nullable=True))
    op.add_column("scores", sa.Column("play_time_seconds", sa.Integer(), nullable=True))
    op.add_column("scores", sa.Column("play_time_source", sa.String(length=32), nullable=True))
    op.add_column(
        "scores",
        sa.Column("submit_exit_classification", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "ck_scores_fail_time_ms_non_negative",
        "scores",
        "fail_time_ms IS NULL OR fail_time_ms >= 0",
    )
    op.create_check_constraint(
        "ck_scores_play_time_seconds_non_negative",
        "scores",
        "play_time_seconds IS NULL OR play_time_seconds >= 0",
    )
    op.create_check_constraint(
        "ck_scores_play_time_source_known",
        "scores",
        _PLAY_TIME_SOURCE_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint("ck_scores_play_time_source_known", "scores", type_="check")
    op.drop_constraint("ck_scores_play_time_seconds_non_negative", "scores", type_="check")
    op.drop_constraint("ck_scores_fail_time_ms_non_negative", "scores", type_="check")
    op.drop_column("scores", "submit_exit_classification")
    op.drop_column("scores", "play_time_source")
    op.drop_column("scores", "play_time_seconds")
    op.drop_column("scores", "fail_time_ms")
