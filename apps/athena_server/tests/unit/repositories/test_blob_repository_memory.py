"""In-memory blob command repositoryの振る舞いを検証する."""

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
    """指定したmetadataからrepository作成用のNewBlobを組み立てる.

    Args:
        sha256 (str): 64文字のlowercase hexadecimal SHA-256値.
        byte_size (int): 保存対象contentのbyte数.
        content_type (str): 保存対象contentのMIME type.
        storage_backend (str): BlobStorageBackendKindへ変換するbackend値.
        storage_key (str): backend内でblobを特定するkey.

    Returns:
        NewBlob: create操作へ渡す検証済みblob metadata.

    Raises:
        ValueError: storage_backendが既知のbackend値へ変換できない場合.
    """
    return NewBlob(
        sha256=sha256,
        byte_size=byte_size,
        content_type=content_type,
        storage_backend=BlobStorageBackendKind(storage_backend),
        storage_key=storage_key,
    )


def _repo() -> InMemoryBlobCommandRepository:
    """独立したcommand stateを持つin-memory blob repositoryを作成する.

    Returns:
        InMemoryBlobCommandRepository: testごとに共有しないrepository instance.
    """
    return InMemoryBlobCommandRepository(InMemoryCommandRepositoryState())


def test_in_memory_blob_repository_satisfies_contract() -> None:
    """In-memory repositoryが必要なblob command contractだけを満たすことを検証する.

    Returns:
        None: runtime Protocol conformanceと禁止操作の不在を検証して完了する.
    """
    repo = _repo()

    assert isinstance(repo, BlobCommandRepository)
    assert not hasattr(repo, "update")
    assert not hasattr(repo, "delete")


async def test_create_assigns_identity_and_creation_time() -> None:
    """createがblobへ連番IDと作成時刻を割り当てることを検証する.

    Returns:
        None: 保存済みblobのmetadataと生成済みidentityを検証して完了する.
    """
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
    """ID lookupが保存済みblobを返し未知IDではNoneになることを検証する.

    Returns:
        None: 成功lookupと欠損lookupのobservable outcomeを検証して完了する.
    """
    repo = _repo()
    created = await repo.create(_new_blob())

    assert await repo.get_by_id(created.id) == created
    assert await repo.get_by_id(9999) is None


async def test_get_by_sha256_returns_created_blob() -> None:
    """SHA-256 lookupが保存済みblobを返し未知hashではNoneになることを検証する.

    Returns:
        None: 成功lookupと欠損lookupのobservable outcomeを検証して完了する.
    """
    repo = _repo()
    created = await repo.create(_new_blob())

    assert await repo.get_by_sha256(VALID_SHA256) == created
    assert await repo.get_by_sha256(OTHER_SHA256) is None


async def test_create_assigns_monotonic_ids() -> None:
    """連続したcreateが単調増加するblob identityを割り当てることを検証する.

    Returns:
        None: 連続作成したblobのID順序を検証して完了する.
    """
    repo = _repo()

    first = await repo.create(_new_blob())
    second = await repo.create(_new_blob(sha256=OTHER_SHA256, storage_key="ff/ff/blob"))

    assert first.id == 1
    assert second.id == 2


async def test_create_rejects_duplicate_sha256_without_creating_second_record() -> None:
    """重複SHA-256を拒否して既存recordを変更しないことを検証する.

    Returns:
        None: DuplicateBlobErrorと既存recordおよび次IDの状態を検証して完了する.
    """
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
