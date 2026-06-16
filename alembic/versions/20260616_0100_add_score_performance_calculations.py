"""Add score performance calculation tables.

Revision ID: 20260616_0100
Revises: 20260613_0023
Create Date: 2026-06-16 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260616_0100"
down_revision: str | None = "20260613_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "score_performance_calculations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("score_id", sa.BigInteger, nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("is_current", sa.Boolean, nullable=False),
        sa.Column("pp", sa.Numeric(12, 6), nullable=True),
        sa.Column("star_rating", sa.Numeric(8, 5), nullable=True),
        sa.Column("calculator_name", sa.String(64), nullable=False),
        sa.Column("calculator_version", sa.String(64), nullable=False),
        sa.Column("formula_profile", sa.String(64), nullable=False),
        sa.Column("beatmap_file_attachment_id", sa.BigInteger, nullable=True),
        sa.Column("beatmap_file_checksum_md5", sa.String(32), nullable=True),
        sa.Column("unavailable_reason", sa.String(128), nullable=True),
        sa.Column("claim_owner", sa.String(128), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["score_id"],
            ["scores.id"],
            name="fk_score_performance_calculations_score_id",
        ),
        sa.ForeignKeyConstraint(
            ["beatmap_file_attachment_id"],
            ["beatmap_file_attachments.id"],
            name="fk_score_performance_calculations_beatmap_file_attachment_id",
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'fetching_file', 'calculating', 'completed', "
            "'unavailable', 'superseded')",
            name="ck_score_performance_state_known",
        ),
        sa.CheckConstraint(
            "state != 'completed' OR "
            "(pp IS NOT NULL AND star_rating IS NOT NULL AND calculated_at IS NOT NULL)",
            name="ck_score_performance_completed_values",
        ),
        sa.CheckConstraint(
            "state != 'unavailable' OR unavailable_reason IS NOT NULL",
            name="ck_score_performance_unavailable_reason",
        ),
    )
    op.create_index(
        "idx_score_performance_current_unique",
        "score_performance_calculations",
        ["score_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )
    op.create_index(
        "idx_score_performance_score_current",
        "score_performance_calculations",
        ["score_id", "is_current"],
    )
    op.create_index(
        "idx_score_performance_state_claim",
        "score_performance_calculations",
        ["state", "claim_expires_at"],
    )
    op.create_index(
        "idx_score_performance_provenance",
        "score_performance_calculations",
        ["calculator_version", "formula_profile"],
    )
    op.create_index(
        "idx_score_performance_file_attachment",
        "score_performance_calculations",
        ["beatmap_file_attachment_id"],
    )

    op.create_table(
        "performance_recalculation_batches",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("filters", JSONB, nullable=False),
        sa.Column("reason_counts", JSONB, nullable=False),
        sa.Column("target_calculator_version", sa.String(64), nullable=False),
        sa.Column("target_formula_profile", sa.String(64), nullable=False),
        sa.Column("candidate_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unavailable_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_performance_recalculation_batches_status",
        "performance_recalculation_batches",
        ["status"],
    )
    op.create_index(
        "idx_performance_recalculation_batches_created",
        "performance_recalculation_batches",
        ["created_at"],
    )

    op.create_table(
        "performance_recalculation_work_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.BigInteger, nullable=False),
        sa.Column("score_id", sa.BigInteger, nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("calculation_id", sa.BigInteger, nullable=True),
        sa.Column("claim_owner", sa.String(128), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["performance_recalculation_batches.id"],
            name="fk_performance_recalculation_work_items_batch_id",
        ),
        sa.ForeignKeyConstraint(
            ["score_id"],
            ["scores.id"],
            name="fk_performance_recalculation_work_items_score_id",
        ),
        sa.ForeignKeyConstraint(
            ["calculation_id"],
            ["score_performance_calculations.id"],
            name="fk_performance_recalculation_work_items_calculation_id",
        ),
    )
    op.create_index(
        "idx_performance_recalculation_work_items_batch_state",
        "performance_recalculation_work_items",
        ["batch_id", "state"],
    )
    op.create_index(
        "idx_performance_recalculation_work_items_state_claim",
        "performance_recalculation_work_items",
        ["state", "claim_expires_at"],
    )
    op.create_index(
        "idx_performance_recalculation_work_items_score_reason",
        "performance_recalculation_work_items",
        ["score_id", "reason"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_performance_recalculation_work_items_score_reason",
        table_name="performance_recalculation_work_items",
    )
    op.drop_index(
        "idx_performance_recalculation_work_items_state_claim",
        table_name="performance_recalculation_work_items",
    )
    op.drop_index(
        "idx_performance_recalculation_work_items_batch_state",
        table_name="performance_recalculation_work_items",
    )
    op.drop_table("performance_recalculation_work_items")
    op.drop_index(
        "idx_performance_recalculation_batches_created",
        table_name="performance_recalculation_batches",
    )
    op.drop_index(
        "idx_performance_recalculation_batches_status",
        table_name="performance_recalculation_batches",
    )
    op.drop_table("performance_recalculation_batches")
    op.drop_index(
        "idx_score_performance_file_attachment",
        table_name="score_performance_calculations",
    )
    op.drop_index("idx_score_performance_provenance", table_name="score_performance_calculations")
    op.drop_index("idx_score_performance_state_claim", table_name="score_performance_calculations")
    op.drop_index(
        "idx_score_performance_score_current", table_name="score_performance_calculations"
    )
    op.drop_index(
        "idx_score_performance_current_unique", table_name="score_performance_calculations"
    )
    op.drop_table("score_performance_calculations")
