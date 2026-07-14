from __future__ import annotations

from datetime import datetime

import pytest

from osu_server.domain.storage.blobs import BlobStorageBackendKind, NewBlob
from osu_server.repositories.interfaces.commands.blobs import (
    BlobCommandRepository,
    DuplicateBlobError,
)
from osu_server.repositories.memory.commands.blobs import InMemoryBlobCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState

VALID_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
OTHER_SHA256 = "f" * 64


def _new_blob(
    *,
    sha256: str = VALID_SHA256,
    byte_size: int = 123,
    content_type: str = "text/plain",
    storage_backend: str = "local",
    storage_key: str = "e3/b0/blob",
) -> NewBlob:
    return NewBlob(
        sha256=sha256,
        byte_size=byte_size,
        content_type=content_type,
        storage_backend=BlobStorageBackendKind(storage_backend),
        storage_key=storage_key,
    )


def _repo() -> InMemoryBlobCommandRepository:
    return InMemoryBlobCommandRepository(InMemoryCommandRepositoryState())


def test_in_memory_blob_repository_satisfies_contract() -> None:
    repo = _repo()

    assert isinstance(repo, BlobCommandRepository)
    assert not hasattr(repo, "update")
    assert not hasattr(repo, "delete")


async def test_create_assigns_identity_and_creation_time() -> None:
    repo = _repo()

    created = await repo.create(_new_blob())

    assert created.id == 1
    assert created.sha256 == VALID_SHA256
    assert created.byte_size == 123
    assert created.content_type == "text/plain"
    assert created.storage_backend == "local"
    assert created.storage_key == "e3/b0/blob"
    assert isinstance(created.created_at, datetime)


async def test_get_by_id_returns_created_blob() -> None:
    repo = _repo()
    created = await repo.create(_new_blob())

    assert await repo.get_by_id(created.id) == created
    assert await repo.get_by_id(9999) is None


async def test_get_by_sha256_returns_created_blob() -> None:
    repo = _repo()
    created = await repo.create(_new_blob())

    assert await repo.get_by_sha256(VALID_SHA256) == created
    assert await repo.get_by_sha256(OTHER_SHA256) is None


async def test_create_assigns_monotonic_ids() -> None:
    repo = _repo()

    first = await repo.create(_new_blob())
    second = await repo.create(_new_blob(sha256=OTHER_SHA256, storage_key="ff/ff/blob"))

    assert first.id == 1
    assert second.id == 2


async def test_create_rejects_duplicate_sha256_without_creating_second_record() -> None:
    repo = _repo()
    created = await repo.create(_new_blob())

    with pytest.raises(DuplicateBlobError) as exc_info:
        _ = await repo.create(
            _new_blob(
                byte_size=456,
                content_type="application/octet-stream",
                storage_key="dupe",
            )
        )

    assert exc_info.value.sha256 == VALID_SHA256
    assert await repo.get_by_sha256(VALID_SHA256) == created
    assert await repo.get_by_id(2) is None
