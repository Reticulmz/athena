"""create users roles tables

Revision ID: 20260522_0811
Revises:
Create Date: 2026-05-22 08:11:00+09:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_0811"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(15), nullable=False),
        sa.Column("safe_username", sa.String(15), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("country", sa.String(2), nullable=False, server_default="XX"),
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

    # roles
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(32), nullable=False, unique=True),
        sa.Column("permissions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
    )

    # user_roles (many-to-many)
    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id"),
            primary_key=True,
        ),
        sa.Column(
            "role_id",
            sa.Integer,
            sa.ForeignKey("roles.id"),
            primary_key=True,
        ),
    )

    # disallowed_usernames
    op.create_table(
        "disallowed_usernames",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("safe_username", sa.String(15), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Seed default roles
    # NORMAL(1) | VERIFIED(2) | UNRESTRICTED(128) = 131
    # All flags = 255
    roles_table = sa.table(
        "roles",
        sa.column("name", sa.String),
        sa.column("permissions", sa.Integer),
        sa.column("position", sa.Integer),
    )
    op.bulk_insert(
        roles_table,
        [
            {"name": "Default", "permissions": 131, "position": 0},
            {"name": "Admin", "permissions": 255, "position": 100},
        ],
    )


def downgrade() -> None:
    op.drop_table("user_roles")
    op.drop_table("disallowed_usernames")
    op.drop_table("roles")
    op.drop_table("users")
