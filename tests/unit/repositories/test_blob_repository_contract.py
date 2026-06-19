from __future__ import annotations

from datetime import UTC, datetime
from typing import get_type_hints

import pytest

from osu_server.domain.storage.blobs import Blob, NewBlob
from osu_server.repositories.interfaces.commands import blobs
from osu_server.repositories.interfaces.commands.blobs import (
    BlobCommandRepository,
    DuplicateBlobError,
)

VALID_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class ContractOnlyBlobRepository:
    async def get_by_id(self, blob_id: int) -> Blob | None:
        _ = blob_id
        return None

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        _ = sha256
        return None

    async def create(self, blob: NewBlob) -> Blob:
        return Blob(
            id=1,
            sha256=blob.sha256,
            byte_size=blob.byte_size,
            content_type=blob.content_type,
            storage_backend=blob.storage_backend,
            storage_key=blob.storage_key,
            created_at=datetime.now(UTC),
        )


def test_blob_repository_runtime_contract_accepts_create_and_lookup_only() -> None:
    repo = ContractOnlyBlobRepository()

    assert isinstance(repo, BlobCommandRepository)
    assert hasattr(BlobCommandRepository, "get_by_id")
    assert hasattr(BlobCommandRepository, "get_by_sha256")
    assert hasattr(BlobCommandRepository, "create")
    assert not hasattr(BlobCommandRepository, "update")
    assert not hasattr(BlobCommandRepository, "delete")


def test_create_contract_accepts_new_blob_and_returns_persisted_blob() -> None:
    hints = get_type_hints(
        BlobCommandRepository.create,
        globalns={**vars(blobs), "Blob": Blob, "NewBlob": NewBlob},
    )

    assert hints["blob"] is NewBlob
    assert hints["return"] is Blob


def test_new_blob_contains_metadata_without_database_id_or_attachment_fields() -> None:
    fields = set(NewBlob.__dataclass_fields__)

    assert fields == {
        "sha256",
        "byte_size",
        "content_type",
        "storage_backend",
        "storage_key",
    }
    assert "id" not in fields
    assert "original_filename" not in fields
    assert "uploaded_by_user_id" not in fields
    assert "owner_id" not in fields
    assert "access_policy" not in fields


def test_new_blob_validates_metadata_before_repository_create() -> None:
    with pytest.raises(ValueError, match="content_type must not be empty"):
        _ = NewBlob(
            sha256=VALID_SHA256,
            byte_size=1,
            content_type="",
            storage_backend="local",
            storage_key="key",
        )

    with pytest.raises(ValueError, match="sha256 must be a 64-character lowercase hexadecimal"):
        _ = NewBlob(
            sha256="short",
            byte_size=1,
            content_type="text/plain",
            storage_backend="local",
            storage_key="key",
        )


def test_duplicate_blob_error_carries_sha256_for_race_resolution() -> None:
    error = DuplicateBlobError(VALID_SHA256)

    assert error.sha256 == VALID_SHA256
    assert VALID_SHA256 in str(error)


def test_contract_module_exports_only_blob_repository_types() -> None:
    assert set(blobs.__all__) == {
        "BlobCommandRepository",
        "DuplicateBlobError",
    }
