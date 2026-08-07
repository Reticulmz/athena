"""replay file attachmentをblob ID参照へ移行するmigration.

Revision ID: 20260612_0022
Revises: 20260612_0021
Create Date: 2026-06-12 12:55:00.000000

"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260612_0022"
down_revision: str | None = "20260612_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replay attachmentのblob_keyをblob_id foreign keyへ置換する.

    Returns:
        None: blob_idのbackfill, 検証, index, foreign key追加を完了したことを示す.

    Raises:
        SQLAlchemyError: blob storage keyに対応するrowがない場合, またはschema変更に失敗した場合.

    Notes:
        text UPDATEはattachmentとblobのjoin backfillを表し, `DO $$` blockはNULL mappingを
        transaction内で検出してmigrationを中断するPostgreSQL固有の検証に使用する.
    """
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
    """Replay attachmentのblob_idをblob_key参照へ戻す.

    Returns:
        None: blob_keyのbackfill, 検証, foreign keyとindexの削除を完了したことを示す.

    Raises:
        SQLAlchemyError: blob IDに対応するrowがない場合, またはschema変更に失敗した場合.

    Notes:
        text UPDATEはblob IDからstorage keyを復元し, `DO $$` blockは復元不能なrowを
        table変更前に検出するPostgreSQL固有の検証に使用する.
    """
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
