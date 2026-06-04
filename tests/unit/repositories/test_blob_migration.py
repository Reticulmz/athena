from pathlib import Path

MIGRATION_PATH = Path("alembic/versions/20260604_1846_create_blobs_table.py")


def test_blob_migration_creates_required_columns_and_constraints() -> None:
    migration = MIGRATION_PATH.read_text()

    assert 'revision: str = "20260604_1846"' in migration
    assert 'down_revision: str | None = "20260525_2100"' in migration
    assert 'op.create_table(\n        "blobs"' in migration
    assert 'sa.Column("sha256", sa.String(64), nullable=False)' in migration
    assert 'sa.Column("byte_size", sa.BigInteger, nullable=False)' in migration
    assert 'sa.Column("content_type", sa.String(255), nullable=False)' in migration
    assert 'sa.Column("storage_backend", sa.String(32), nullable=False)' in migration
    assert 'sa.Column("storage_key", sa.String(512), nullable=False)' in migration
    assert 'sa.UniqueConstraint("sha256", name="uq_blobs_sha256")' in migration
    assert (
        'sa.CheckConstraint("byte_size >= 0", name="ck_blobs_byte_size_non_negative")' in migration
    )


def test_blob_migration_downgrade_removes_blobs_table() -> None:
    migration = MIGRATION_PATH.read_text()

    assert 'op.drop_table("blobs")' in migration
