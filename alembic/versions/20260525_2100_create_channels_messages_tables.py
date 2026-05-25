"""create channels messages tables

Revision ID: 20260525_2100
Revises: 20260522_0811
Create Date: 2026-05-25 21:00:00+09:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260525_2100"
down_revision: str | None = "20260522_0811"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # channels
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(32), nullable=False, unique=True),
        sa.Column("topic", sa.String(256), nullable=False, server_default=""),
        sa.Column("channel_type", sa.String(16), nullable=False, server_default="public"),
        sa.Column("read_privileges", sa.Integer, nullable=False, server_default="1"),
        sa.Column("write_privileges", sa.Integer, nullable=False, server_default="1"),
        sa.Column("manage_privileges", sa.Integer, nullable=False, server_default="16"),
        sa.Column("auto_join", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("rate_limit_messages", sa.Integer, nullable=True),
        sa.Column("rate_limit_window", sa.Integer, nullable=True),
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

    # channel_messages
    op.create_table(
        "channel_messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "sender_id",
            sa.Integer,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            sa.Integer,
            sa.ForeignKey("channels.id"),
            nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_channel_messages_channel_created",
        "channel_messages",
        ["channel_id", "created_at"],
    )

    # private_messages
    op.create_table(
        "private_messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "sender_id",
            sa.Integer,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "target_user_id",
            sa.Integer,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_private_messages_target_created",
        "private_messages",
        ["target_user_id", "created_at"],
    )
    op.create_index(
        "idx_private_messages_sender_created",
        "private_messages",
        ["sender_id", "created_at"],
    )

    # Seed BanchoBot user (id=1)
    users_table = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("username", sa.String),
        sa.column("safe_username", sa.String),
        sa.column("email", sa.String),
        sa.column("password_hash", sa.String),
        sa.column("country", sa.String),
    )
    op.bulk_insert(
        users_table,
        [
            {
                "id": 1,
                "username": "BanchoBot",
                "safe_username": "banchobot",
                "email": "bot@internal",
                "password_hash": "!invalid",
                "country": "XX",
            },
        ],
    )

    # Seed default channels
    channels_table = sa.table(
        "channels",
        sa.column("name", sa.String),
        sa.column("topic", sa.String),
        sa.column("read_privileges", sa.Integer),
        sa.column("write_privileges", sa.Integer),
        sa.column("auto_join", sa.Boolean),
    )
    op.bulk_insert(
        channels_table,
        [
            {
                "name": "#osu",
                "topic": "General discussion",
                "read_privileges": 1,
                "write_privileges": 1,
                "auto_join": True,
            },
            {
                "name": "#announce",
                "topic": "Announcements",
                "read_privileges": 1,
                "write_privileges": 16,
                "auto_join": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("idx_private_messages_sender_created", table_name="private_messages")
    op.drop_index("idx_private_messages_target_created", table_name="private_messages")
    op.drop_table("private_messages")
    op.drop_index("idx_channel_messages_channel_created", table_name="channel_messages")
    op.drop_table("channel_messages")

    # Remove seeded channels and BanchoBot user
    op.execute("DELETE FROM channels WHERE name IN ('#osu', '#announce')")
    op.execute("DELETE FROM users WHERE id = 1")

    op.drop_table("channels")
