"""Add current user stats projection.

Revision ID: 20260630_0200
Revises: 20260630_0100
Create Date: 2026-06-30 02:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260630_0200"
down_revision: str | None = "20260630_0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXCLUDED_INITIAL_STATS_MODS = 8320


def upgrade() -> None:
    _ = op.create_table(
        "current_user_stats",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ruleset", sa.SmallInteger(), nullable=False),
        sa.Column("playstyle", sa.SmallInteger(), nullable=False),
        sa.Column("pp", sa.Numeric(12, 6), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=False),
        sa.Column("play_count", sa.Integer(), nullable=False),
        sa.Column("ranked_score", sa.BigInteger(), nullable=False),
        sa.Column("total_score", sa.BigInteger(), nullable=False),
        sa.Column("max_combo", sa.Integer(), nullable=False),
        sa.Column("play_time_seconds", sa.BigInteger(), nullable=True),
        sa.Column("count_300", sa.BigInteger(), nullable=False),
        sa.Column("count_100", sa.BigInteger(), nullable=False),
        sa.Column("count_50", sa.BigInteger(), nullable=False),
        sa.Column("count_geki", sa.BigInteger(), nullable=False),
        sa.Column("count_katu", sa.BigInteger(), nullable=False),
        sa.Column("count_miss", sa.BigInteger(), nullable=False),
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
        sa.CheckConstraint("pp >= 0", name="ck_current_user_stats_pp_non_negative"),
        sa.CheckConstraint(
            "accuracy >= 0 AND accuracy <= 1",
            name="ck_current_user_stats_accuracy_ratio",
        ),
        sa.CheckConstraint(
            "play_count >= 0",
            name="ck_current_user_stats_play_count_non_negative",
        ),
        sa.CheckConstraint(
            "ranked_score >= 0",
            name="ck_current_user_stats_ranked_score_non_negative",
        ),
        sa.CheckConstraint(
            "total_score >= 0",
            name="ck_current_user_stats_total_score_non_negative",
        ),
        sa.CheckConstraint(
            "max_combo >= 0",
            name="ck_current_user_stats_max_combo_non_negative",
        ),
        sa.CheckConstraint(
            "play_time_seconds IS NULL OR play_time_seconds >= 0",
            name="ck_current_user_stats_play_time_seconds_non_negative",
        ),
        sa.CheckConstraint(
            "count_300 >= 0",
            name="ck_current_user_stats_count_300_non_negative",
        ),
        sa.CheckConstraint(
            "count_100 >= 0",
            name="ck_current_user_stats_count_100_non_negative",
        ),
        sa.CheckConstraint(
            "count_50 >= 0",
            name="ck_current_user_stats_count_50_non_negative",
        ),
        sa.CheckConstraint(
            "count_geki >= 0",
            name="ck_current_user_stats_count_geki_non_negative",
        ),
        sa.CheckConstraint(
            "count_katu >= 0",
            name="ck_current_user_stats_count_katu_non_negative",
        ),
        sa.CheckConstraint(
            "count_miss >= 0",
            name="ck_current_user_stats_count_miss_non_negative",
        ),
        sa.PrimaryKeyConstraint("user_id", "ruleset", "playstyle"),
    )
    op.create_index(
        "idx_current_user_stats_rank_support",
        "current_user_stats",
        ["ruleset", "playstyle", sa.text("pp DESC"), "user_id"],
    )
    _backfill_current_user_stats()


def downgrade() -> None:
    op.drop_index("idx_current_user_stats_rank_support", table_name="current_user_stats")
    op.drop_table("current_user_stats")


def _backfill_current_user_stats() -> None:
    op.execute(
        sa.text(
            """
            WITH scoped_scores AS (
                SELECT *
                FROM scores
                WHERE (mods & :excluded_mods) = 0
            ),
            score_aggregates AS (
                SELECT
                    user_id,
                    ruleset,
                    playstyle,
                    count(id)::integer AS play_count,
                    coalesce(sum(score), 0)::bigint AS total_score,
                    coalesce(max(max_combo), 0)::integer AS max_combo,
                    sum(play_time_seconds)::bigint AS play_time_seconds,
                    coalesce(sum(n300), 0)::bigint AS count_300,
                    coalesce(sum(n100), 0)::bigint AS count_100,
                    coalesce(sum(n50), 0)::bigint AS count_50,
                    coalesce(sum(geki), 0)::bigint AS count_geki,
                    coalesce(sum(katu), 0)::bigint AS count_katu,
                    coalesce(sum(miss), 0)::bigint AS count_miss
                FROM scoped_scores
                GROUP BY user_id, ruleset, playstyle
            ),
            ranked_score_candidates AS (
                SELECT
                    user_id,
                    ruleset,
                    playstyle,
                    beatmap_id,
                    max(score)::bigint AS score
                FROM scoped_scores
                WHERE passed = true
                  AND leaderboard_eligible_at_submission = true
                GROUP BY user_id, ruleset, playstyle, beatmap_id
            ),
            ranked_scores AS (
                SELECT
                    user_id,
                    ruleset,
                    playstyle,
                    coalesce(sum(score), 0)::bigint AS ranked_score
                FROM ranked_score_candidates
                GROUP BY user_id, ruleset, playstyle
            ),
            weighted_best_rows AS (
                SELECT
                    user_id,
                    ruleset,
                    playstyle,
                    pp,
                    row_number() OVER (
                        PARTITION BY user_id, ruleset, playstyle
                        ORDER BY pp DESC, submitted_at ASC, score_id ASC
                    ) AS row_number
                FROM beatmap_performance_bests
            ),
            pp_totals AS (
                SELECT
                    user_id,
                    ruleset,
                    playstyle,
                    coalesce(
                        sum(pp * power(0.95::numeric, (row_number - 1)::numeric))
                            FILTER (WHERE row_number <= 200),
                        0
                    ) AS pp
                FROM weighted_best_rows
                GROUP BY user_id, ruleset, playstyle
            )
            INSERT INTO current_user_stats (
                user_id,
                ruleset,
                playstyle,
                pp,
                accuracy,
                play_count,
                ranked_score,
                total_score,
                max_combo,
                play_time_seconds,
                count_300,
                count_100,
                count_50,
                count_geki,
                count_katu,
                count_miss
            )
            SELECT
                score_aggregates.user_id,
                score_aggregates.ruleset,
                score_aggregates.playstyle,
                coalesce(pp_totals.pp, 0) AS pp,
                CASE
                    WHEN score_aggregates.ruleset = 0 THEN
                        CASE
                            WHEN (
                                score_aggregates.count_300
                                + score_aggregates.count_100
                                + score_aggregates.count_50
                                + score_aggregates.count_miss
                            ) = 0 THEN 0.0
                            ELSE (
                                score_aggregates.count_300 * 300.0
                                + score_aggregates.count_100 * 100.0
                                + score_aggregates.count_50 * 50.0
                            ) / (
                                (
                                    score_aggregates.count_300
                                    + score_aggregates.count_100
                                    + score_aggregates.count_50
                                    + score_aggregates.count_miss
                                ) * 300.0
                            )
                        END
                    WHEN score_aggregates.ruleset = 1 THEN
                        CASE
                            WHEN (
                                score_aggregates.count_300
                                + score_aggregates.count_100
                                + score_aggregates.count_miss
                            ) = 0 THEN 0.0
                            ELSE (
                                score_aggregates.count_300 * 300.0
                                + score_aggregates.count_100 * 150.0
                            ) / (
                                (
                                    score_aggregates.count_300
                                    + score_aggregates.count_100
                                    + score_aggregates.count_miss
                                ) * 300.0
                            )
                        END
                    WHEN score_aggregates.ruleset = 2 THEN
                        CASE
                            WHEN (
                                score_aggregates.count_300
                                + score_aggregates.count_100
                                + score_aggregates.count_50
                                + score_aggregates.count_katu
                                + score_aggregates.count_miss
                            ) = 0 THEN 0.0
                            ELSE (
                                score_aggregates.count_300
                                + score_aggregates.count_100
                                + score_aggregates.count_50
                            )::double precision / (
                                score_aggregates.count_300
                                + score_aggregates.count_100
                                + score_aggregates.count_50
                                + score_aggregates.count_katu
                                + score_aggregates.count_miss
                            )::double precision
                        END
                    ELSE
                        CASE
                            WHEN (
                                score_aggregates.count_300
                                + score_aggregates.count_100
                                + score_aggregates.count_50
                                + score_aggregates.count_geki
                                + score_aggregates.count_katu
                                + score_aggregates.count_miss
                            ) = 0 THEN 0.0
                            ELSE (
                                score_aggregates.count_geki * 300.0
                                + score_aggregates.count_300 * 300.0
                                + score_aggregates.count_katu * 200.0
                                + score_aggregates.count_100 * 100.0
                                + score_aggregates.count_50 * 50.0
                            ) / (
                                (
                                    score_aggregates.count_300
                                    + score_aggregates.count_100
                                    + score_aggregates.count_50
                                    + score_aggregates.count_geki
                                    + score_aggregates.count_katu
                                    + score_aggregates.count_miss
                                ) * 300.0
                            )
                        END
                END AS accuracy,
                score_aggregates.play_count,
                coalesce(ranked_scores.ranked_score, 0) AS ranked_score,
                score_aggregates.total_score,
                score_aggregates.max_combo,
                score_aggregates.play_time_seconds,
                score_aggregates.count_300,
                score_aggregates.count_100,
                score_aggregates.count_50,
                score_aggregates.count_geki,
                score_aggregates.count_katu,
                score_aggregates.count_miss
            FROM score_aggregates
            LEFT JOIN ranked_scores
              ON ranked_scores.user_id = score_aggregates.user_id
             AND ranked_scores.ruleset = score_aggregates.ruleset
             AND ranked_scores.playstyle = score_aggregates.playstyle
            LEFT JOIN pp_totals
              ON pp_totals.user_id = score_aggregates.user_id
             AND pp_totals.ruleset = score_aggregates.ruleset
             AND pp_totals.playstyle = score_aggregates.playstyle
            """
        ).bindparams(excluded_mods=_EXCLUDED_INITIAL_STATS_MODS)
    )
