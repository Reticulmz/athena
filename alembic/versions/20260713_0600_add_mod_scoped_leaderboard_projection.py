"""leaderboard projectionをraw Mod scope単位へ再構築するmigration.

Revision ID: 20260713_0600
Revises: 20260712_0500
Create Date: 2026-07-13 06:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260713_0600"
down_revision: str | None = "20260712_0500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECTION_TABLE = "beatmap_leaderboard_user_bests"
_SCOPE_UNIQUE_CONSTRAINT = "uq_beatmap_leaderboard_user_bests_scope"
_MODS_CHECK_CONSTRAINT = "ck_beatmap_leaderboard_user_bests_mods_non_negative"


def upgrade() -> None:
    """projectionをraw Mod bitflagごとのuser bestへ移行する.

    Returns:
        None: schema変更とprojection再構築が完了したことを示す.
    """
    op.add_column(
        _PROJECTION_TABLE,
        sa.Column("mods", sa.Integer(), nullable=True),
    )
    op.drop_constraint(
        _SCOPE_UNIQUE_CONSTRAINT,
        _PROJECTION_TABLE,
        type_="unique",
    )

    _delete_projection_rows()
    _rebuild_projection(partition_by_mods=True)

    op.alter_column(
        _PROJECTION_TABLE,
        "mods",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_check_constraint(
        _MODS_CHECK_CONSTRAINT,
        _PROJECTION_TABLE,
        sa.column("mods", sa.Integer()) >= 0,
    )
    op.create_unique_constraint(
        _SCOPE_UNIQUE_CONSTRAINT,
        _PROJECTION_TABLE,
        ["beatmap_id", "ruleset", "playstyle", "user_id", "mods"],
    )


def downgrade() -> None:
    """projectionをGlobal all-modsのuser bestへ戻す.

    Returns:
        None: 旧schemaとGlobal projectionの再構築が完了したことを示す.
    """
    op.drop_constraint(
        _SCOPE_UNIQUE_CONSTRAINT,
        _PROJECTION_TABLE,
        type_="unique",
    )

    _delete_projection_rows()
    _rebuild_projection(partition_by_mods=False)

    op.create_unique_constraint(
        _SCOPE_UNIQUE_CONSTRAINT,
        _PROJECTION_TABLE,
        ["beatmap_id", "ruleset", "playstyle", "user_id"],
    )
    op.drop_constraint(
        _MODS_CHECK_CONSTRAINT,
        _PROJECTION_TABLE,
        type_="check",
    )
    op.drop_column(_PROJECTION_TABLE, "mods")


def _delete_projection_rows() -> None:
    projection = sa.table(
        _PROJECTION_TABLE,
        sa.column("id", sa.BigInteger()),
    )
    op.execute(sa.delete(projection))


def _rebuild_projection(*, partition_by_mods: bool) -> None:
    projection = sa.table(
        _PROJECTION_TABLE,
        sa.column("beatmap_id", sa.Integer()),
        sa.column("beatmap_checksum", sa.String(length=32)),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
        sa.column("mods", sa.Integer()),
        sa.column("score_id", sa.BigInteger()),
        sa.column("score", sa.Integer()),
        sa.column("submitted_at", sa.DateTime(timezone=True)),
    )
    scores = sa.table(
        "scores",
        sa.column("id", sa.BigInteger()),
        sa.column("beatmap_id", sa.Integer()),
        sa.column("beatmap_checksum", sa.String(length=32)),
        sa.column("ruleset", sa.SmallInteger()),
        sa.column("playstyle", sa.SmallInteger()),
        sa.column("user_id", sa.Integer()),
        sa.column("mods", sa.Integer()),
        sa.column("score", sa.Integer()),
        sa.column("submitted_at", sa.DateTime(timezone=True)),
        sa.column("passed", sa.Boolean()),
        sa.column("leaderboard_eligible_at_submission", sa.Boolean()),
    )
    beatmaps = sa.table(
        "beatmaps",
        sa.column("id", sa.Integer()),
        sa.column("checksum_md5", sa.String(length=32)),
    )

    partition_columns = [
        scores.c.beatmap_id,
        scores.c.ruleset,
        scores.c.playstyle,
        scores.c.user_id,
    ]
    if partition_by_mods:
        partition_columns.append(scores.c.mods)

    ranked = (
        sa.select(
            scores.c.beatmap_id,
            scores.c.beatmap_checksum,
            scores.c.ruleset,
            scores.c.playstyle,
            scores.c.user_id,
            scores.c.mods,
            scores.c.id.label("score_id"),
            scores.c.score,
            scores.c.submitted_at,
            sa.func.row_number()
            .over(
                partition_by=tuple(partition_columns),
                order_by=(
                    scores.c.score.desc(),
                    scores.c.submitted_at.asc(),
                    scores.c.id.asc(),
                ),
            )
            .label("candidate_rank"),
        )
        .select_from(
            scores.join(
                beatmaps,
                sa.and_(
                    beatmaps.c.id == scores.c.beatmap_id,
                    beatmaps.c.checksum_md5 == scores.c.beatmap_checksum,
                ),
            )
        )
        .where(
            scores.c.passed.is_(True),
            scores.c.leaderboard_eligible_at_submission.is_(True),
        )
        .subquery("ranked_mod_scoped_leaderboard_projection")
    )
    op.execute(
        sa.insert(projection).from_select(
            (
                "beatmap_id",
                "beatmap_checksum",
                "ruleset",
                "playstyle",
                "user_id",
                "mods",
                "score_id",
                "score",
                "submitted_at",
            ),
            sa.select(
                ranked.c.beatmap_id,
                ranked.c.beatmap_checksum,
                ranked.c.ruleset,
                ranked.c.playstyle,
                ranked.c.user_id,
                ranked.c.mods,
                ranked.c.score_id,
                ranked.c.score,
                ranked.c.submitted_at,
            ).where(ranked.c.candidate_rank == 1),
        )
    )
