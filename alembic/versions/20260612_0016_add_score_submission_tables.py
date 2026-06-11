"""Add score submission tables

Revision ID: 20260612_0016
Revises: 20260604_2001
Create Date: 2026-06-12 00:16:04.097138

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260612_0016"
down_revision: str | None = "20260604_2001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scores",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("beatmap_id", sa.Integer, nullable=False),
        sa.Column("beatmap_checksum", sa.String(32), nullable=False),
        sa.Column("online_checksum", sa.String(32), nullable=False, unique=True),
        sa.Column("ruleset", sa.SmallInteger, nullable=False),
        sa.Column("playstyle", sa.SmallInteger, nullable=False),
        sa.Column("mods", sa.Integer, nullable=False),
        sa.Column("n300", sa.Integer, nullable=False),
        sa.Column("n100", sa.Integer, nullable=False),
        sa.Column("n50", sa.Integer, nullable=False),
        sa.Column("geki", sa.Integer, nullable=False),
        sa.Column("katu", sa.Integer, nullable=False),
        sa.Column("miss", sa.Integer, nullable=False),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("max_combo", sa.Integer, nullable=False),
        sa.Column("accuracy", sa.Float, nullable=False),
        sa.Column("grade", sa.String(2), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("perfect", sa.Boolean, nullable=False),
        sa.Column("client_version", sa.String(32), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_scores_user_id", "scores", ["user_id"])
    op.create_index("idx_scores_beatmap_id", "scores", ["beatmap_id"])
    op.create_index("idx_scores_submitted_at", "scores", ["submitted_at"])

    op.create_table(
        "score_submissions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("beatmap_checksum", sa.String(32), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("result_snapshot", JSONB, nullable=True),
    )
    op.create_index("idx_submissions_user_id", "score_submissions", ["user_id"])
    op.create_index("idx_submissions_submitted_at", "score_submissions", ["submitted_at"])

    op.create_table(
        "replays",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("score_id", sa.BigInteger, nullable=False),
        sa.Column("blob_key", sa.String(255), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("byte_size", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_replays_score_id", "replays", ["score_id"])
    op.create_foreign_key("fk_replays_score_id", "replays", "scores", ["score_id"], ["id"])


def downgrade() -> None:
    op.drop_table("replays")
    op.drop_table("score_submissions")
    op.drop_table("scores")
