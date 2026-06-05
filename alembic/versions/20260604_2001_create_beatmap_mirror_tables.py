"""create beatmap mirror tables

Revision ID: 20260604_2001
Revises: 20260604_1846
Create Date: 2026-06-04 20:01:00+09:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260604_2001"
down_revision: str | None = "20260604_1846"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "beatmapsets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("artist", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("creator", sa.String(255), nullable=False),
        sa.Column("artist_unicode", sa.String(255), nullable=True),
        sa.Column("title_unicode", sa.String(255), nullable=True),
        sa.Column("official_status", sa.String(32), nullable=False),
        sa.Column("official_status_source", sa.String(64), nullable=False),
        sa.Column("official_status_verified", sa.Boolean, nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=True),
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

    op.create_table(
        "beatmaps",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("beatmapset_id", sa.Integer, sa.ForeignKey("beatmapsets.id"), nullable=False),
        sa.Column("checksum_md5", sa.String(32), nullable=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("version", sa.String(255), nullable=False),
        sa.Column("total_length", sa.Integer, nullable=True),
        sa.Column("hit_length", sa.Integer, nullable=True),
        sa.Column("max_combo", sa.Integer, nullable=True),
        sa.Column("bpm", sa.Numeric(8, 3), nullable=True),
        sa.Column("cs", sa.Numeric(5, 2), nullable=True),
        sa.Column("od", sa.Numeric(5, 2), nullable=True),
        sa.Column("ar", sa.Numeric(5, 2), nullable=True),
        sa.Column("hp", sa.Numeric(5, 2), nullable=True),
        sa.Column("difficulty_rating", sa.Numeric(6, 3), nullable=True),
        sa.Column("official_status", sa.String(32), nullable=False),
        sa.Column("official_status_source", sa.String(64), nullable=False),
        sa.Column("official_status_verified", sa.Boolean, nullable=False),
        sa.Column("local_status_override", sa.String(32), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_refresh_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("checksum_md5", name="uq_beatmaps_checksum_md5"),
    )
    op.create_index("idx_beatmaps_beatmapset_id", "beatmaps", ["beatmapset_id"])
    op.create_index("idx_beatmaps_checksum_md5", "beatmaps", ["checksum_md5"])

    op.create_table(
        "beatmap_file_attachments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("beatmap_id", sa.Integer, sa.ForeignKey("beatmaps.id"), nullable=False),
        sa.Column("blob_id", sa.Integer, sa.ForeignKey("blobs.id"), nullable=False),
        sa.Column("checksum_md5", sa.String(32), nullable=False),
        sa.Column("verified_md5", sa.String(32), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "beatmap_id",
            "checksum_md5",
            name="uq_beatmap_file_attachments_beatmap_checksum_md5",
        ),
    )
    op.create_index(
        "idx_beatmap_file_attachments_beatmap", "beatmap_file_attachments", ["beatmap_id"]
    )
    op.create_index("idx_beatmap_file_attachments_blob", "beatmap_file_attachments", ["blob_id"])

    op.create_table(
        "beatmap_fetch_states",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("pending_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("target_type", "target_key", name="uq_beatmap_fetch_states_target"),
    )
    op.create_index(
        "idx_beatmap_fetch_states_target_lookup",
        "beatmap_fetch_states",
        ["target_type", "target_key", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_beatmap_fetch_states_target_lookup", table_name="beatmap_fetch_states")
    op.drop_table("beatmap_fetch_states")
    op.drop_index("idx_beatmap_file_attachments_blob", table_name="beatmap_file_attachments")
    op.drop_index("idx_beatmap_file_attachments_beatmap", table_name="beatmap_file_attachments")
    op.drop_table("beatmap_file_attachments")
    op.drop_index("idx_beatmaps_checksum_md5", table_name="beatmaps")
    op.drop_index("idx_beatmaps_beatmapset_id", table_name="beatmaps")
    op.drop_table("beatmaps")
    op.drop_table("beatmapsets")
