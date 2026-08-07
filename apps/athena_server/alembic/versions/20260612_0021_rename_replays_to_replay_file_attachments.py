"""replays tableをreplay_file_attachmentsへrenameするmigration.

Revision ID: 20260612_0021
Revises: 20260612_0016
Create Date: 2026-06-12 12:25:00.000000

"""

from typing import TYPE_CHECKING

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260612_0021"
down_revision: str | None = "20260612_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replay table, index, constraintをattachment terminologyへrenameする.

    Returns:
        None: replay_file_attachments用のtable名とdatabase object名への移行を完了し,
            呼び出し側へ値を返さずに終了する.

    Notes:
        PostgreSQLの`ALTER ... RENAME`と条件付き`DO $$` blockは, 存在しない自動命名
        constraintを安全に扱いながらrenameするAlembic operation APIがないため使用する.
    """
    op.rename_table("replays", "replay_file_attachments")
    op.execute(
        "ALTER INDEX IF EXISTS idx_replays_score_id RENAME TO idx_replay_file_attachments_score_id"
    )
    op.execute(
        "ALTER TABLE replay_file_attachments "
        "RENAME CONSTRAINT fk_replays_score_id "
        "TO fk_replay_file_attachments_score_id"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'replays_checksum_sha256_key'
            ) THEN
                ALTER TABLE replay_file_attachments
                RENAME CONSTRAINT replays_checksum_sha256_key
                TO replay_file_attachments_checksum_sha256_key;
            END IF;
        END $$;
        """,
    )


def downgrade() -> None:
    """Replay attachmentのtable, index, constraintを旧名称へ戻す.

    Returns:
        None: replays用のtable名とdatabase object名の復元を完了し, 呼び出し側へ値を返さずに
            終了する.

    Notes:
        PostgreSQLの`ALTER ... RENAME`と条件付き`DO $$` blockは, 環境ごとに異なり得る
        自動命名constraintの存在を確認してから復元するために使用する.
    """
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'replay_file_attachments_checksum_sha256_key'
            ) THEN
                ALTER TABLE replay_file_attachments
                RENAME CONSTRAINT replay_file_attachments_checksum_sha256_key
                TO replays_checksum_sha256_key;
            END IF;
        END $$;
        """,
    )
    op.execute(
        "ALTER TABLE replay_file_attachments "
        "RENAME CONSTRAINT fk_replay_file_attachments_score_id "
        "TO fk_replays_score_id"
    )
    op.execute(
        "ALTER INDEX IF EXISTS idx_replay_file_attachments_score_id RENAME TO idx_replays_score_id"
    )
    op.rename_table("replay_file_attachments", "replays")
