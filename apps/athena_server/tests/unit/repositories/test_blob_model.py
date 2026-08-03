"""BlobModelの永続化schema契約を検証する."""

from typing import TYPE_CHECKING, cast

from sqlalchemy import CheckConstraint, Column, String, Table, UniqueConstraint
from sqlalchemy import Enum as SQLAlchemyEnum

from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models import BlobModel

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement


def _table() -> Table:
    """BlobModelに対応するSQLAlchemy tableを取得する.

    Returns:
        Table: BlobModelが登録したtable metadata.
    """
    return cast("Table", BlobModel.__table__)


def _column(table: Table, name: str) -> Column[object]:
    """指定名のcolumnをtable metadataから取得する.

    Args:
        table (Table): columnを保持するSQLAlchemy table.
        name (str): 取得するcolumn名.

    Returns:
        Column[object]: 指定名に対応するcolumn metadata.
    """
    return cast("Column[object]", table.c[name])


def _string_length(column: Column[object]) -> int | None:
    """文字列columnに設定された最大長を取得する.

    Args:
        column (Column[object]): String型として検証するcolumn metadata.

    Returns:
        int | None: SQLAlchemy String型に設定された最大長.
    """
    return cast("String", column.type).length


def _enum_type(column: Column[object]) -> SQLAlchemyEnum:
    """Enum columnのSQLAlchemy enum型設定を検証用に取得する.

    Args:
        column (Column[object]): SQLAlchemyEnum型であることを期待するcolumn metadata.

    Returns:
        SQLAlchemyEnum: columnに設定されたenum型metadata.

    Raises:
        AssertionError: columnの型がSQLAlchemyEnumではない場合.
    """
    enum_type = column.type
    assert isinstance(enum_type, SQLAlchemyEnum)
    return enum_type


def test_blob_model_is_registered_for_migration_discovery() -> None:
    """BlobModelがmigration discovery用metadataへ登録される契約を検証する.

    Returns:
        None: table名とmetadata登録を検証して完了する.
    """
    assert BlobModel.__tablename__ == "blobs"
    assert Base.metadata.tables["blobs"] is _table()


def test_blob_model_defines_immutable_metadata_columns() -> None:
    """Blob metadataのcolumn構成と不変制約を検証する.

    Returns:
        None: 必須columnと長さおよびnull制約とenum制約を検証して完了する.
    """
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
    storage_backend_type = _enum_type(_column(table, "storage_backend"))
    assert cast("bool", storage_backend_type.native_enum) is False
    assert cast("bool", storage_backend_type.create_constraint) is True
    assert cast("bool", storage_backend_type.validate_strings) is True
    assert storage_backend_type.name == "ck_blobs_storage_backend_known"
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_blobs_storage_backend_known"
        for constraint in table.constraints
    )
    assert not _column(table, "storage_key").nullable
    assert _string_length(_column(table, "storage_key")) == 512
    assert not _column(table, "created_at").nullable


def test_blob_storage_does_not_register_shared_attachment_table() -> None:
    """Blob storageが共有attachment tableを所有しない境界を検証する.

    Returns:
        None: 禁止されたtable名がmetadataに存在しないことを検証して完了する.
    """
    shared_attachment_table_names = {
        "blob_attachments",
        "blob_attachment",
        "attachments",
        "polymorphic_blob_attachments",
    }

    assert shared_attachment_table_names.isdisjoint(Base.metadata.tables)


def test_blob_model_enforces_unique_sha256_and_non_negative_size() -> None:
    """BlobのSHA-256一意性とbyte size下限のdatabase制約を検証する.

    Returns:
        None: unique constraintとcheck constraintの定義を検証して完了する.
    """
    table = _table()

    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    check_constraints = {
        constraint.name: str(
            cast("ColumnElement[bool]", constraint.sqltext).compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert unique_constraints["uq_blobs_sha256"] == ("sha256",)
    assert check_constraints["ck_blobs_byte_size_non_negative"] == "byte_size >= 0"
