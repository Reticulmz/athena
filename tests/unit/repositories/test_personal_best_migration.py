from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy import Column, ForeignKeyConstraint, Table

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models import PersonalBestModel

if TYPE_CHECKING:
    from sqlalchemy.dialects.postgresql import ENUM

MIGRATION_PATH = Path("alembic/versions/20260617_0101_add_personal_bests.py")


def _column(table: Table, name: str) -> Column[object]:
    return cast("Column[object]", table.c[name])


def _enum_values(column: Column[object]) -> tuple[str, ...]:
    return tuple(cast("ENUM", column.type).enums)


def _foreign_key_constraints(table: Table) -> dict[str, tuple[str, str]]:
    constraints: dict[str, tuple[str, str]] = {}
    for constraint in table.constraints:
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name is not None:
            source_column = next(iter(constraint.columns)).name
            target_column = cast("str", next(iter(constraint.elements)).target_fullname)
            constraints[str(constraint.name)] = (source_column, target_column)
    return constraints


def _indexes(table: Table) -> dict[str, tuple[tuple[str, ...], bool]]:
    indexes: dict[str, tuple[tuple[str, ...], bool]] = {}
    for index in table.indexes:
        if index.name is not None:
            indexes[index.name] = (tuple(column.name for column in index.columns), index.unique)
    return indexes


def test_personal_best_migration_creates_projection_table_and_indexes() -> None:
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260617_0101"' in migration
    assert 'down_revision: str | None = "20260616_0100"' in migration
    assert 'op.create_table(\n        "personal_bests"' in migration
    assert "fk_personal_bests_score_id" in migration
    assert "idx_personal_bests_scope_unique" in migration
    assert "idx_personal_bests_score_id" in migration
    assert "idx_personal_bests_beatmap_category" in migration
    assert 'op.drop_table("personal_bests")' in migration


def test_personal_best_model_is_registered_for_metadata_discovery() -> None:
    assert PersonalBestModel.__tablename__ == "personal_bests"
    assert Base.metadata.tables["personal_bests"] is PersonalBestModel.__table__


def test_personal_best_metadata_matches_projection_contract() -> None:
    table = cast("Table", PersonalBestModel.__table__)

    assert _column(table, "id").primary_key
    assert not _column(table, "user_id").nullable
    assert not _column(table, "beatmap_id").nullable
    assert not _column(table, "ruleset").nullable
    assert not _column(table, "playstyle").nullable
    assert not _column(table, "category").nullable
    assert not _column(table, "score_id").nullable
    assert not _column(table, "ranking_value").nullable
    assert _enum_values(_column(table, "category")) == (
        "global",
        "country",
        "selected_mods",
        "friends",
    )
    assert _foreign_key_constraints(table)["fk_personal_bests_score_id"] == (
        "score_id",
        "scores.id",
    )
    indexes = _indexes(table)
    assert indexes["idx_personal_bests_scope_unique"] == (
        ("user_id", "beatmap_id", "ruleset", "playstyle", "category"),
        True,
    )
    assert indexes["idx_personal_bests_score_id"] == (("score_id",), False)
    assert indexes["idx_personal_bests_beatmap_category"] == (
        ("beatmap_id", "category"),
        False,
    )
