from __future__ import annotations

from pathlib import Path
from typing import cast

from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint, Table

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models import UserFriendRelationshipModel

MIGRATION_PATH = Path("alembic/versions/20260617_0102_create_user_friend_relationships.py")


def _column(table: Table, name: str) -> Column[object]:
    return cast("Column[object]", table.c[name])


def _foreign_key_constraints(table: Table) -> dict[str, tuple[str, str, str | None]]:
    constraints: dict[str, tuple[str, str, str | None]] = {}
    for constraint in table.constraints:
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name is not None:
            source_column = next(iter(constraint.columns)).name
            target_column = cast("str", next(iter(constraint.elements)).target_fullname)
            ondelete = next(iter(constraint.elements)).ondelete
            constraints[str(constraint.name)] = (source_column, target_column, ondelete)
    return constraints


def test_friend_relationship_migration_creates_directed_relationship_table() -> None:
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260617_0102"' in migration
    assert 'down_revision: str | None = "20260617_0101"' in migration
    assert 'op.create_table(\n        "user_friend_relationships"' in migration
    assert "fk_user_friend_relationships_owner_user_id" in migration
    assert "fk_user_friend_relationships_target_user_id" in migration
    assert "ck_user_friend_relationships_no_self" in migration
    assert 'op.drop_table("user_friend_relationships")' in migration


def test_friend_relationship_model_is_registered_for_metadata_discovery() -> None:
    assert UserFriendRelationshipModel.__tablename__ == "user_friend_relationships"
    assert (
        Base.metadata.tables["user_friend_relationships"] is UserFriendRelationshipModel.__table__
    )


def test_friend_relationship_metadata_matches_storage_contract() -> None:
    table = cast("Table", UserFriendRelationshipModel.__table__)

    assert _column(table, "owner_user_id").primary_key
    assert _column(table, "target_user_id").primary_key
    assert not _column(table, "created_at").nullable
    assert _foreign_key_constraints(table) == {
        "fk_user_friend_relationships_owner_user_id": (
            "owner_user_id",
            "users.id",
            "CASCADE",
        ),
        "fk_user_friend_relationships_target_user_id": (
            "target_user_id",
            "users.id",
            "CASCADE",
        ),
    }
    check_constraints = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_user_friend_relationships_no_self" in check_constraints
