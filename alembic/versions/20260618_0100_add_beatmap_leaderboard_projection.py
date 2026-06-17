"""Add beatmap leaderboard projection schema.

Revision ID: 20260618_0100
Revises: 20260617_0102
Create Date: 2026-06-18 01:00:00.000000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260618_0100"
down_revision: str | None = "20260617_0102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scores",
        sa.Column(
            "leaderboard_eligible_at_submission",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE scores
            SET leaderboard_eligible_at_submission = true
            WHERE passed = true
              AND beatmap_status_at_submission IN ('ranked', 'approved', 'loved', 'qualified')
            """
        )
    )
    op.create_index(
        "idx_scores_leaderboard_rebuild_candidate",
        "scores",
        [
            "beatmap_id",
            "ruleset",
            "playstyle",
            "user_id",
            "leaderboard_eligible_at_submission",
            "passed",
            "score",
            "submitted_at",
            "id",
        ],
    )

    op.create_table(
        "beatmap_leaderboard_user_bests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("beatmap_id", sa.Integer(), nullable=False),
        sa.Column("ruleset", sa.SmallInteger(), nullable=False),
        sa.Column("playstyle", sa.SmallInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mod_filter_key", sa.Integer(), nullable=True),
        sa.Column("score_id", sa.BigInteger(), nullable=False),
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
            "mod_filter_key IS NULL OR mod_filter_key >= 0",
            name="ck_beatmap_leaderboard_user_bests_mod_filter_key_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["score_id"],
            ["scores.id"],
            name="fk_beatmap_leaderboard_user_bests_score_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                source_missing_count bigint;
            BEGIN
                SELECT count(*)
                INTO source_missing_count
                FROM personal_bests pb
                LEFT JOIN scores s ON s.id = pb.score_id
                WHERE s.id IS NULL
                  AND pb.category IN ('global', 'country', 'friends');

                RAISE NOTICE
                    'beatmap_leaderboard_legacy_personal_best_skipped source_missing=%',
                    source_missing_count;
            END $$;
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH legacy_personal_best_candidates AS (
                SELECT
                    s.beatmap_id AS beatmap_id,
                    s.ruleset AS ruleset,
                    s.playstyle AS playstyle,
                    s.user_id AS user_id,
                    NULL AS mod_filter_key,
                    s.id AS score_id,
                    s.score AS score,
                    s.submitted_at AS submitted_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.beatmap_id, s.ruleset, s.playstyle, s.user_id
                        ORDER BY s.score DESC, s.submitted_at ASC, s.id ASC
                    ) AS candidate_rank
                FROM personal_bests pb
                INNER JOIN scores s ON s.id = pb.score_id
                WHERE pb.category IN ('global', 'country', 'friends')
                  AND s.leaderboard_eligible_at_submission = true
            )
            INSERT INTO beatmap_leaderboard_user_bests (
                beatmap_id,
                ruleset,
                playstyle,
                user_id,
                mod_filter_key,
                score_id,
                score,
                submitted_at
            )
            SELECT
                beatmap_id,
                ruleset,
                playstyle,
                user_id,
                mod_filter_key,
                score_id,
                score,
                submitted_at
            FROM legacy_personal_best_candidates
            WHERE candidate_rank = 1
            """
        )
    )
    op.create_index(
        "idx_beatmap_leaderboard_user_bests_scope_unique",
        "beatmap_leaderboard_user_bests",
        [
            "beatmap_id",
            "ruleset",
            "playstyle",
            "user_id",
            sa.text("COALESCE(mod_filter_key, -1)"),
        ],
        unique=True,
    )
    op.create_index(
        "idx_beatmap_leaderboard_user_bests_ordering",
        "beatmap_leaderboard_user_bests",
        [
            "beatmap_id",
            "ruleset",
            "playstyle",
            sa.text("COALESCE(mod_filter_key, -1)"),
            sa.text("score DESC"),
            sa.text("submitted_at ASC"),
            sa.text("score_id ASC"),
        ],
    )
    op.create_index(
        "idx_beatmap_leaderboard_user_bests_user_rebuild",
        "beatmap_leaderboard_user_bests",
        ["user_id", "beatmap_id", "ruleset", "playstyle"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_beatmap_leaderboard_user_bests_user_rebuild",
        table_name="beatmap_leaderboard_user_bests",
    )
    op.drop_index(
        "idx_beatmap_leaderboard_user_bests_ordering",
        table_name="beatmap_leaderboard_user_bests",
    )
    op.drop_index(
        "idx_beatmap_leaderboard_user_bests_scope_unique",
        table_name="beatmap_leaderboard_user_bests",
    )
    op.drop_table("beatmap_leaderboard_user_bests")
    op.drop_index("idx_scores_leaderboard_rebuild_candidate", table_name="scores")
    op.drop_column("scores", "leaderboard_eligible_at_submission")
