"""Blob command repositoryの公開contractを検証する."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import get_type_hints

import pytest

from osu_server.domain.storage.blobs import Blob, BlobStorageBackendKind, NewBlob
from osu_server.repositories.interfaces.commands import blobs
from osu_server.repositories.interfaces.commands.blobs import (
    BlobCommandRepository,
    DuplicateBlobError,
)

VALID_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class ContractOnlyBlobRepository:
    """BlobCommandRepositoryのruntime conformanceだけを表すfake repository."""

    async def get_by_id(self, blob_id: int) -> Blob | None:
        """IDによるlookup contractを値なしで実装する.

        Args:
            blob_id (int): lookup対象のblob識別子.

        Returns:
            Blob | None: このcontract-only fakeでは常にNone.
        """
        _ = blob_id
        return None

    async def get_by_sha256(self, sha256: str) -> Blob | None:
        """SHA-256によるlookup contractを値なしで実装する.

        Args:
            sha256 (str): lookup対象のblob SHA-256値.

        Returns:
            Blob | None: このcontract-only fakeでは常にNone.
        """
        _ = sha256
        return None

    async def create(self, blob: NewBlob) -> Blob:
        """新規blob metadataを永続化済みblobとして返すcontractを実装する.

        Args:
            blob (NewBlob): 永続化前に検証済みのblob metadata.

        Returns:
            Blob: 固定IDと現在時刻を持つ永続化済みblob.
        """
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
    """Blob command repositoryがcreateとlookupだけを公開するcontractを検証する.

    Returns:
        None: runtime Protocol conformanceと禁止操作の不在を検証して完了する.
    """
    repo = ContractOnlyBlobRepository()

    assert isinstance(repo, BlobCommandRepository)
    assert hasattr(BlobCommandRepository, "get_by_id")
    assert hasattr(BlobCommandRepository, "get_by_sha256")
    assert hasattr(BlobCommandRepository, "create")
    assert not hasattr(BlobCommandRepository, "update")
    assert not hasattr(BlobCommandRepository, "delete")


def test_create_contract_accepts_new_blob_and_returns_persisted_blob() -> None:
    """createがNewBlobを受け取りBlobを返す型contractを検証する.

    Returns:
        None: Protocol methodの解決済み型hintを検証して完了する.
    """
    hints = get_type_hints(
        BlobCommandRepository.create,
        globalns={**vars(blobs), "Blob": Blob, "NewBlob": NewBlob},
    )

    assert hints["blob"] is NewBlob
    assert hints["return"] is Blob


def test_new_blob_contains_metadata_without_database_id_or_attachment_fields() -> None:
    """NewBlobが永続化前metadataだけを持つ値objectであることを検証する.

    Returns:
        None: 必須fieldと禁止された永続化fieldの不在を検証して完了する.
    """
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
    """NewBlobがrepository create前に不正metadataを拒否することを検証する.

    Returns:
        None: 空content typeと不正SHA-256値のValueErrorを検証して完了する.
    """
    with pytest.raises(ValueError, match="content_type must not be empty"):
        _ = NewBlob(
            sha256=VALID_SHA256,
            byte_size=1,
            content_type="",
            storage_backend=BlobStorageBackendKind.LOCAL,
            storage_key="key",
        )

    with pytest.raises(ValueError, match="sha256 must be a 64-character lowercase hexadecimal"):
        _ = NewBlob(
            sha256="short",
            byte_size=1,
            content_type="text/plain",
            storage_backend=BlobStorageBackendKind.LOCAL,
            storage_key="key",
        )


def test_duplicate_blob_error_carries_sha256_for_race_resolution() -> None:
    """DuplicateBlobErrorが競合解決に必要なSHA-256を保持することを検証する.

    Returns:
        None: error attributeと表示文字列にSHA-256が含まれることを検証して完了する.
    """
    error = DuplicateBlobError(VALID_SHA256)

    assert error.sha256 == VALID_SHA256
    assert VALID_SHA256 in str(error)


def test_contract_module_exports_only_blob_repository_types() -> None:
    """Blob contract moduleがrepository型だけをexportする境界を検証する.

    Returns:
        None: public export集合がrepository contractとdomain errorだけであることを検証して完了する.
    """
    assert set(blobs.__all__) == {
        "BlobCommandRepository",
        "DuplicateBlobError",
    }
