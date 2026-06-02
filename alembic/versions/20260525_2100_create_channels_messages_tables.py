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

    # channel_role_overrides (Discord-style role-based ACL)
    op.create_table(
        "channel_role_overrides",
        sa.Column("channel_id", sa.Integer, sa.ForeignKey("channels.id"), primary_key=True),
        sa.Column("role_id", sa.Integer, sa.ForeignKey("roles.id"), primary_key=True),
        sa.Column("can_read", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("can_write", sa.Boolean, nullable=False, server_default=sa.text("true")),
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

    # Seed BanchoBot user with reserved user id=1.
    # id=1 is the protocol-level BanchoBot identity (osu! client convention).
    op.execute(
        """
        INSERT INTO users (id, username, safe_username, email, password_hash, country)
        VALUES (1, 'BanchoBot', 'banchobot', 'bot@internal', '!invalid', 'XX')
        ON CONFLICT DO NOTHING
        """
    )

    # Seed default channels
    channels_table = sa.table(
        "channels",
        sa.column("name", sa.String),
        sa.column("topic", sa.String),
        sa.column("auto_join", sa.Boolean),
    )
    op.bulk_insert(
        channels_table,
        [
            {"name": "#osu", "topic": "General discussion", "auto_join": True},
            {"name": "#announce", "topic": "Announcements", "auto_join": True},
        ],
    )

    # Seed channel role overrides (Default role id=1, Admin role id=2)
    overrides_table = sa.table(
        "channel_role_overrides",
        sa.column("channel_id", sa.Integer),
        sa.column("role_id", sa.Integer),
        sa.column("can_read", sa.Boolean),
        sa.column("can_write", sa.Boolean),
    )
    op.bulk_insert(
        overrides_table,
        [
            # #osu (id=1): Default role → read+write (public)
            {"channel_id": 1, "role_id": 1, "can_read": True, "can_write": True},
            # #announce (id=2): Default role → read-only
            {"channel_id": 2, "role_id": 1, "can_read": True, "can_write": False},
            # #announce (id=2): Admin role → read+write
            {"channel_id": 2, "role_id": 2, "can_read": True, "can_write": True},
        ],
    )


def downgrade() -> None:
    op.drop_index("idx_private_messages_sender_created", table_name="private_messages")
    op.drop_index("idx_private_messages_target_created", table_name="private_messages")
    op.drop_table("private_messages")
    op.drop_index("idx_channel_messages_channel_created", table_name="channel_messages")
    op.drop_table("channel_messages")

    # Remove seeded data (overrides first due to FK)
    op.execute("DELETE FROM channel_role_overrides")
    op.execute("DELETE FROM channels WHERE name IN ('#osu', '#announce')")
    op.execute("DELETE FROM users WHERE safe_username = 'banchobot' AND email = 'bot@internal'")

    op.drop_table("channel_role_overrides")
    op.drop_table("channels")
