from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, override

import pytest
from sqlalchemy.exc import IntegrityError

from osu_server.domain.storage.blobs import Blob, BlobStorageBackendKind, NewBlob
from osu_server.repositories.interfaces.commands.blobs import (
    BlobCommandRepository,
    DuplicateBlobError,
)
from osu_server.repositories.sqlalchemy.commands.blobs import SQLAlchemyBlobCommandRepository
from osu_server.repositories.sqlalchemy.models.blob import BlobModel

if TYPE_CHECKING:
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.base import Executable

VALID_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
OTHER_SHA256 = "f" * 64
CREATED_AT = datetime(2026, 6, 4, 18, 46, tzinfo=UTC)


class BlobResult:
    _blob: BlobModel | None

    def __init__(self, blob: BlobModel | None) -> None:
        self._blob = blob

    def scalar_one_or_none(self) -> BlobModel | None:
        return self._blob


class FakeSession(AbstractAsyncContextManager["FakeSession"]):
    added: list[object]
    flushes: int
    refreshed: list[object]
    get_result: BlobModel | None
    execute_result: BlobModel | None
    flush_error: IntegrityError | None

    def __init__(
        self,
        *,
        get_result: BlobModel | None = None,
        execute_result: BlobModel | None = None,
        flush_error: IntegrityError | None = None,
    ) -> None:
        self.added = []
        self.flushes = 0
        self.refreshed = []
        self.get_result = get_result
        self.execute_result = execute_result
        self.flush_error = flush_error

    @override
    async def __aenter__(self) -> FakeSession:
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type
        _ = exc
        _ = traceback

    async def get(self, model_type: type[BlobModel], blob_id: int) -> BlobModel | None:
        _ = model_type
        _ = blob_id
        return self.get_result

    async def execute(self, statement: Executable) -> BlobResult:
        _ = statement
        return BlobResult(self.execute_result)

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error
        self.flushes += 1

    async def refresh(self, instance: object) -> None:
        assert isinstance(instance, BlobModel)
        instance.id = 1
        instance.created_at = CREATED_AT
        self.refreshed.append(instance)


def _new_blob(*, sha256: str = VALID_SHA256) -> NewBlob:
    return NewBlob(
        sha256=sha256,
        byte_size=123,
        content_type="text/plain",
        storage_backend=BlobStorageBackendKind.LOCAL,
        storage_key="e3/b0/blob",
    )


def _blob_model(*, id: int = 1, sha256: str = VALID_SHA256) -> BlobModel:  # noqa: A002
    return BlobModel(
        id=id,
        sha256=sha256,
        byte_size=123,
        content_type="text/plain",
        storage_backend="local",
        storage_key="e3/b0/blob",
        created_at=CREATED_AT,
    )


def _repo(session: FakeSession) -> SQLAlchemyBlobCommandRepository:
    return SQLAlchemyBlobCommandRepository(cast("AsyncSession", cast("object", session)))


def test_sqlalchemy_blob_repository_satisfies_contract() -> None:
    repo = _repo(FakeSession())

    assert isinstance(repo, BlobCommandRepository)
    assert not hasattr(repo, "update")
    assert not hasattr(repo, "delete")


async def test_create_persists_blob_model_and_returns_domain_blob() -> None:
    session = FakeSession()
    repo = _repo(session)

    created = await repo.create(_new_blob())

    assert created == Blob(
        id=1,
        sha256=VALID_SHA256,
        byte_size=123,
        content_type="text/plain",
        storage_backend=BlobStorageBackendKind.LOCAL,
        storage_key="e3/b0/blob",
        created_at=CREATED_AT,
    )
    assert session.flushes == 1
    assert len(session.refreshed) == 1
    added = session.added[0]
    assert isinstance(added, BlobModel)
    assert added.sha256 == VALID_SHA256


async def test_get_by_id_maps_model_to_domain_blob() -> None:
    repo = _repo(FakeSession(get_result=_blob_model()))

    assert await repo.get_by_id(1) == Blob(
        id=1,
        sha256=VALID_SHA256,
        byte_size=123,
        content_type="text/plain",
        storage_backend=BlobStorageBackendKind.LOCAL,
        storage_key="e3/b0/blob",
        created_at=CREATED_AT,
    )


async def test_get_by_sha256_maps_model_to_domain_blob() -> None:
    repo = _repo(FakeSession(execute_result=_blob_model(sha256=OTHER_SHA256)))

    result = await repo.get_by_sha256(OTHER_SHA256)

    assert result is not None
    assert result.sha256 == OTHER_SHA256


async def test_missing_blob_returns_none() -> None:
    repo = _repo(FakeSession())

    assert await repo.get_by_id(9999) is None
    assert await repo.get_by_sha256(OTHER_SHA256) is None


async def test_duplicate_sha256_raises_duplicate_blob_error() -> None:
    session = FakeSession(flush_error=IntegrityError("insert", {}, Exception("duplicate")))
    repo = _repo(session)

    with pytest.raises(DuplicateBlobError) as exc_info:
        _ = await repo.create(_new_blob())

    assert exc_info.value.sha256 == VALID_SHA256
    assert session.flushes == 0
