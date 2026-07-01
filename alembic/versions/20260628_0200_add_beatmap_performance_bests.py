"""Add beatmap performance best projection.

Revision ID: 20260628_0200
Revises: 20260628_0100
Create Date: 2026-06-28 02:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260628_0200"
down_revision: str | None = "20260628_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXCLUDED_INITIAL_STATS_MODS = 8320


def upgrade() -> None:
    _ = op.create_table(
        "beatmap_performance_bests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("beatmap_id", sa.Integer(), nullable=False),
        sa.Column("ruleset", sa.SmallInteger(), nullable=False),
        sa.Column("playstyle", sa.SmallInteger(), nullable=False),
        sa.Column("score_id", sa.BigInteger(), nullable=False),
        sa.Column("performance_calculation_id", sa.BigInteger(), nullable=False),
        sa.Column("pp", sa.Numeric(12, 6), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "pp >= 0",
            name="ck_beatmap_performance_bests_pp_non_negative",
        ),
        sa.CheckConstraint(
            "accuracy >= 0 AND accuracy <= 1",
            name="ck_beatmap_performance_bests_accuracy_ratio",
        ),
        sa.CheckConstraint(
            "score >= 0",
            name="ck_beatmap_performance_bests_score_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["score_id"],
            ["scores.id"],
            name="fk_beatmap_performance_bests_score_id",
        ),
        sa.ForeignKeyConstraint(
            ["performance_calculation_id"],
            ["score_performance_calculations.id"],
            name="fk_beatmap_performance_bests_performance_calculation_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_beatmap_performance_bests_scope_unique",
        "beatmap_performance_bests",
        ["user_id", "beatmap_id", "ruleset", "playstyle"],
        unique=True,
    )
    op.create_index(
        "idx_beatmap_performance_bests_rank_support",
        "beatmap_performance_bests",
        ["ruleset", "playstyle", sa.text("pp DESC"), "user_id"],
    )
    op.create_index(
        "idx_beatmap_performance_bests_user_rebuild",
        "beatmap_performance_bests",
        ["user_id", "beatmap_id", "ruleset", "playstyle"],
    )
    _backfill_beatmap_performance_bests()


def downgrade() -> None:
    op.drop_index(
        "idx_beatmap_performance_bests_user_rebuild",
        table_name="beatmap_performance_bests",
    )
    op.drop_index(
        "idx_beatmap_performance_bests_rank_support",
        table_name="beatmap_performance_bests",
    )
    op.drop_index(
        "idx_beatmap_performance_bests_scope_unique",
        table_name="beatmap_performance_bests",
    )
    op.drop_table("beatmap_performance_bests")


def _backfill_beatmap_performance_bests() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO beatmap_performance_bests (
                user_id,
                beatmap_id,
                ruleset,
                playstyle,
                score_id,
                performance_calculation_id,
                pp,
                accuracy,
                score,
                submitted_at
            )
            SELECT
                ranked.user_id,
                ranked.beatmap_id,
                ranked.ruleset,
                ranked.playstyle,
                ranked.score_id,
                ranked.performance_calculation_id,
                ranked.pp,
                ranked.accuracy,
                ranked.score,
                ranked.submitted_at
            FROM (
                SELECT
                    scores.user_id,
                    scores.beatmap_id,
                    scores.ruleset,
                    scores.playstyle,
                    scores.id AS score_id,
                    score_performance_calculations.id AS performance_calculation_id,
                    score_performance_calculations.pp,
                    scores.accuracy,
                    scores.score,
                    scores.submitted_at,
                    row_number() OVER (
                        PARTITION BY
                            scores.user_id,
                            scores.beatmap_id,
                            scores.ruleset,
                            scores.playstyle
                        ORDER BY
                            score_performance_calculations.pp DESC,
                            scores.submitted_at ASC,
                            scores.id ASC
                    ) AS row_number
                FROM scores
                JOIN score_performance_calculations
                  ON score_performance_calculations.score_id = scores.id
                 AND score_performance_calculations.is_current = true
                WHERE scores.passed = true
                  AND scores.leaderboard_eligible_at_submission = true
                  AND (scores.mods & :excluded_mods) = 0
                  AND score_performance_calculations.state = 'completed'
                  AND score_performance_calculations.pp IS NOT NULL
            ) AS ranked
            WHERE ranked.row_number = 1
            """
        ).bindparams(excluded_mods=_EXCLUDED_INITIAL_STATS_MODS)
    )
