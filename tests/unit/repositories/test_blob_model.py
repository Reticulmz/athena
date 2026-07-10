from typing import TYPE_CHECKING, cast

from sqlalchemy import CheckConstraint, Column, String, Table, UniqueConstraint

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models import BlobModel

if TYPE_CHECKING:
    from sqlalchemy.dialects.postgresql import ENUM


def _table() -> Table:
    return cast("Table", BlobModel.__table__)


def _column(table: Table, name: str) -> Column[object]:
    return cast("Column[object]", table.c[name])


def _string_length(column: Column[object]) -> int | None:
    return cast("String", column.type).length


def _enum_name(column: Column[object]) -> str:
    return str(cast("ENUM", column.type).name)


def test_blob_model_is_registered_for_migration_discovery() -> None:
    assert BlobModel.__tablename__ == "blobs"
    assert Base.metadata.tables["blobs"] is _table()


def test_blob_model_defines_immutable_metadata_columns() -> None:
    table = _table()

    assert set(table.columns.keys()) == {
        "id",
        "sha256",
        "byte_size",
        "content_type",
        "storage_backend",
        "storage_key",
        "created_at",
    }
    assert not _column(table, "sha256").nullable
    assert _string_length(_column(table, "sha256")) == 64
    assert not _column(table, "byte_size").nullable
    assert not _column(table, "content_type").nullable
    assert _string_length(_column(table, "content_type")) == 255
    assert not _column(table, "storage_backend").nullable
    assert _enum_name(_column(table, "storage_backend")) == "blob_storage_backend"
    assert not _column(table, "storage_key").nullable
    assert _string_length(_column(table, "storage_key")) == 512
    assert not _column(table, "created_at").nullable


def test_blob_storage_does_not_register_shared_attachment_table() -> None:
    shared_attachment_table_names = {
        "blob_attachments",
        "blob_attachment",
        "attachments",
        "polymorphic_blob_attachments",
    }

    assert shared_attachment_table_names.isdisjoint(Base.metadata.tables)


def test_blob_model_enforces_unique_sha256_and_non_negative_size() -> None:
    table = _table()

    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    check_constraints = {
        constraint.name: str(cast("object", constraint.sqltext))
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert unique_constraints["uq_blobs_sha256"] == ("sha256",)
    assert check_constraints["ck_blobs_byte_size_non_negative"] == "byte_size >= 0"
