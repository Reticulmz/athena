from pathlib import Path
from typing import TYPE_CHECKING, cast

from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint, Numeric, String, Table
from sqlalchemy.dialects.postgresql import JSONB

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models import (
    PerformanceRecalculationBatchModel,
    PerformanceRecalculationWorkItemModel,
    ScorePerformanceCalculationModel,
)

if TYPE_CHECKING:
    from decimal import Decimal

MIGRATION_PATH = Path("alembic/versions/20260616_0100_add_score_performance_calculations.py")


def _column(table: Table, name: str) -> Column[object]:
    return cast("Column[object]", table.c[name])


def _string_length(column: Column[object]) -> int | None:
    return cast("String", column.type).length


def _numeric_precision_scale(column: Column[object]) -> tuple[int | None, int | None]:
    numeric = cast("Numeric[Decimal]", column.type)
    return numeric.precision, numeric.scale


def _check_constraints(table: Table) -> set[str]:
    return {
        str(constraint.name)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def _foreign_key_constraints(table: Table) -> dict[str, tuple[str, str]]:
    constraints: dict[str, tuple[str, str]] = {}
    for constraint in table.constraints:
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name is not None:
            constraint_name = cast("str", constraint.name)
            source_column = next(iter(constraint.columns)).name
            target_column = cast("str", next(iter(constraint.elements)).target_fullname)
            constraints[constraint_name] = (source_column, target_column)
    return constraints


def _indexes(table: Table) -> dict[str, tuple[tuple[str, ...], bool]]:
    indexes: dict[str, tuple[tuple[str, ...], bool]] = {}
    for index in table.indexes:
        if index.name is not None:
            indexes[index.name] = (tuple(column.name for column in index.columns), index.unique)
    return indexes


def test_score_performance_migration_creates_tables_constraints_and_indexes() -> None:
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260616_0100"' in migration
    assert 'down_revision: str | None = "20260613_0023"' in migration
    assert 'op.create_table(\n        "score_performance_calculations"' in migration
    assert 'op.create_table(\n        "performance_recalculation_batches"' in migration
    assert 'op.create_table(\n        "performance_recalculation_work_items"' in migration
    assert "ck_score_performance_state_known" in migration
    assert "ck_score_performance_completed_values" in migration
    assert "ck_score_performance_unavailable_reason" in migration
    assert "idx_score_performance_current_unique" in migration
    assert 'postgresql_where=sa.text("is_current = true")' in migration
    assert "idx_score_performance_state_claim" in migration
    assert "idx_score_performance_provenance" in migration
    assert "idx_performance_recalculation_batches_status" in migration
    assert "idx_performance_recalculation_work_items_batch_state" in migration
    assert "idx_performance_recalculation_work_items_state_claim" in migration
    assert 'op.drop_table("performance_recalculation_work_items")' in migration
    assert 'op.drop_table("performance_recalculation_batches")' in migration
    assert 'op.drop_table("score_performance_calculations")' in migration


def test_score_performance_models_are_registered_for_metadata_discovery() -> None:
    assert ScorePerformanceCalculationModel.__tablename__ == "score_performance_calculations"
    assert PerformanceRecalculationBatchModel.__tablename__ == "performance_recalculation_batches"
    assert (
        PerformanceRecalculationWorkItemModel.__tablename__
        == "performance_recalculation_work_items"
    )
    assert (
        Base.metadata.tables["score_performance_calculations"]
        is ScorePerformanceCalculationModel.__table__
    )
    assert (
        Base.metadata.tables["performance_recalculation_batches"]
        is PerformanceRecalculationBatchModel.__table__
    )
    assert (
        Base.metadata.tables["performance_recalculation_work_items"]
        is PerformanceRecalculationWorkItemModel.__table__
    )


def test_score_performance_calculation_metadata_matches_current_contract() -> None:
    table = cast("Table", ScorePerformanceCalculationModel.__table__)

    assert _column(table, "id").primary_key
    assert not _column(table, "score_id").nullable
    assert not _column(table, "state").nullable
    assert not _column(table, "is_current").nullable
    assert _numeric_precision_scale(_column(table, "pp")) == (12, 6)
    assert _numeric_precision_scale(_column(table, "star_rating")) == (8, 5)
    assert _string_length(_column(table, "calculator_name")) == 64
    assert _string_length(_column(table, "calculator_version")) == 64
    assert _string_length(_column(table, "formula_profile")) == 64
    assert _string_length(_column(table, "beatmap_file_checksum_md5")) == 32
    assert not _column(table, "attempt_count").nullable
    assert _foreign_key_constraints(table)["fk_score_performance_calculations_score_id"] == (
        "score_id",
        "scores.id",
    )
    assert _foreign_key_constraints(table)[
        "fk_score_performance_calculations_beatmap_file_attachment_id"
    ] == ("beatmap_file_attachment_id", "beatmap_file_attachments.id")
    assert {
        "ck_score_performance_state_known",
        "ck_score_performance_completed_values",
        "ck_score_performance_unavailable_reason",
    }.issubset(_check_constraints(table))
    indexes = _indexes(table)
    assert indexes["idx_score_performance_current_unique"] == (("score_id",), True)
    assert indexes["idx_score_performance_score_current"] == (("score_id", "is_current"), False)
    assert indexes["idx_score_performance_state_claim"] == (
        ("state", "claim_expires_at"),
        False,
    )
    assert indexes["idx_score_performance_provenance"] == (
        ("calculator_version", "formula_profile"),
        False,
    )
    assert indexes["idx_score_performance_file_attachment"] == (
        ("beatmap_file_attachment_id",),
        False,
    )


def test_recalculation_batch_and_work_item_metadata_match_durable_work_contract() -> None:
    batches = cast("Table", PerformanceRecalculationBatchModel.__table__)
    work_items = cast("Table", PerformanceRecalculationWorkItemModel.__table__)

    assert isinstance(_column(batches, "filters").type, JSONB)
    assert isinstance(_column(batches, "reason_counts").type, JSONB)
    assert not _column(batches, "status").nullable
    assert not _column(batches, "target_calculator_version").nullable
    assert not _column(batches, "target_formula_profile").nullable
    assert not _column(batches, "candidate_count").nullable
    assert not _column(batches, "completed_count").nullable
    assert not _column(batches, "unavailable_count").nullable
    assert _indexes(batches)["idx_performance_recalculation_batches_status"] == (
        ("status",),
        False,
    )
    assert _indexes(batches)["idx_performance_recalculation_batches_created"] == (
        ("created_at",),
        False,
    )

    assert not _column(work_items, "batch_id").nullable
    assert not _column(work_items, "score_id").nullable
    assert not _column(work_items, "reason").nullable
    assert not _column(work_items, "state").nullable
    assert not _column(work_items, "attempt_count").nullable
    assert _foreign_key_constraints(work_items)[
        "fk_performance_recalculation_work_items_batch_id"
    ] == ("batch_id", "performance_recalculation_batches.id")
    assert _foreign_key_constraints(work_items)[
        "fk_performance_recalculation_work_items_score_id"
    ] == ("score_id", "scores.id")
    assert _foreign_key_constraints(work_items)[
        "fk_performance_recalculation_work_items_calculation_id"
    ] == ("calculation_id", "score_performance_calculations.id")
    assert _indexes(work_items)["idx_performance_recalculation_work_items_batch_state"] == (
        ("batch_id", "state"),
        False,
    )
    assert _indexes(work_items)["idx_performance_recalculation_work_items_state_claim"] == (
        ("state", "claim_expires_at"),
        False,
    )
    assert _indexes(work_items)["idx_performance_recalculation_work_items_score_reason"] == (
        ("score_id", "reason"),
        False,
    )
