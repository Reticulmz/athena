"""Add beatmap submission counters.

Revision ID: 20260630_0300
Revises: 20260630_0200
Create Date: 2026-06-30 03:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260630_0300"
down_revision: str | None = "20260630_0200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "beatmaps",
        sa.Column(
            "play_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "beatmaps",
        sa.Column(
            "pass_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE beatmaps
            SET
                play_count = counts.play_count,
                pass_count = counts.pass_count
            FROM (
                SELECT
                    beatmap_id,
                    count(id)::bigint AS play_count,
                    count(id) FILTER (WHERE passed IS TRUE)::bigint AS pass_count
                FROM scores
                GROUP BY beatmap_id
            ) AS counts
            WHERE beatmaps.id = counts.beatmap_id
            """
        )
    )
    op.create_check_constraint(
        "ck_beatmaps_play_count_non_negative",
        "beatmaps",
        "play_count >= 0",
    )
    op.create_check_constraint(
        "ck_beatmaps_pass_count_non_negative",
        "beatmaps",
        "pass_count >= 0",
    )
    op.create_check_constraint(
        "ck_beatmaps_pass_count_lte_play_count",
        "beatmaps",
        "pass_count <= play_count",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_beatmaps_pass_count_lte_play_count",
        "beatmaps",
        type_="check",
    )
    op.drop_constraint(
        "ck_beatmaps_pass_count_non_negative",
        "beatmaps",
        type_="check",
    )
    op.drop_constraint(
        "ck_beatmaps_play_count_non_negative",
        "beatmaps",
        type_="check",
    )
    op.drop_column("beatmaps", "pass_count")
    op.drop_column("beatmaps", "play_count")
