"""Use blob_id for replay file attachments.

Revision ID: 20260612_0022
Revises: 20260612_0021
Create Date: 2026-06-12 12:55:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260612_0022"
down_revision: str | None = "20260612_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("replay_file_attachments", sa.Column("blob_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE replay_file_attachments AS attachment
        SET blob_id = blob.id
        FROM blobs AS blob
        WHERE attachment.blob_key = blob.storage_key
        """,
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM replay_file_attachments
                WHERE blob_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'missing blobs.storage_key rows for replay_file_attachments.blob_key';
            END IF;
        END $$;
        """,
    )
    op.alter_column(
        "replay_file_attachments",
        "blob_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_index(
        "idx_replay_file_attachments_blob_id",
        "replay_file_attachments",
        ["blob_id"],
    )
    op.create_foreign_key(
        "fk_replay_file_attachments_blob_id",
        "replay_file_attachments",
        "blobs",
        ["blob_id"],
        ["id"],
    )
    op.drop_column("replay_file_attachments", "blob_key")


def downgrade() -> None:
    op.add_column(
        "replay_file_attachments",
        sa.Column("blob_key", sa.String(255), nullable=True),
    )
    op.execute(
        """
        UPDATE replay_file_attachments AS attachment
        SET blob_key = blob.storage_key
        FROM blobs AS blob
        WHERE attachment.blob_id = blob.id
        """,
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM replay_file_attachments
                WHERE blob_key IS NULL
            ) THEN
                RAISE EXCEPTION
                    'missing blobs.id rows for replay_file_attachments.blob_id';
            END IF;
        END $$;
        """,
    )
    op.alter_column(
        "replay_file_attachments",
        "blob_key",
        existing_type=sa.String(255),
        nullable=False,
    )
    op.drop_constraint(
        "fk_replay_file_attachments_blob_id",
        "replay_file_attachments",
        type_="foreignkey",
    )
    op.drop_index(
        "idx_replay_file_attachments_blob_id",
        table_name="replay_file_attachments",
    )
    op.drop_column("replay_file_attachments", "blob_id")
