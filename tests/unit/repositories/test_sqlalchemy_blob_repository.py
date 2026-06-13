from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, override

import pytest
from sqlalchemy.exc import IntegrityError

from osu_server.domain.storage.blobs import Blob
from osu_server.repositories.interfaces.blob_repository import (
    BlobRepository,
    DuplicateBlobError,
    NewBlob,
)
from osu_server.repositories.sqlalchemy.blob_repository import SQLAlchemyBlobRepository
from osu_server.repositories.sqlalchemy.models.blob import BlobModel

if TYPE_CHECKING:
    from types import TracebackType

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
    commits: int
    rollbacks: int
    refreshed: list[object]
    get_result: BlobModel | None
    execute_result: BlobModel | None
    commit_error: IntegrityError | None

    def __init__(
        self,
        *,
        get_result: BlobModel | None = None,
        execute_result: BlobModel | None = None,
        commit_error: IntegrityError | None = None,
    ) -> None:
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshed = []
        self.get_result = get_result
        self.execute_result = execute_result
        self.commit_error = commit_error

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

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, instance: object) -> None:
        assert isinstance(instance, BlobModel)
        instance.id = 1
        instance.created_at = CREATED_AT
        self.refreshed.append(instance)


class FakeSessionFactory:
    _session: FakeSession

    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def __call__(self) -> FakeSession:
        return self._session


def _new_blob(*, sha256: str = VALID_SHA256) -> NewBlob:
    return NewBlob(
        sha256=sha256,
        byte_size=123,
        content_type="text/plain",
        storage_backend="local",
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


def test_sqlalchemy_blob_repository_satisfies_contract() -> None:
    repo = SQLAlchemyBlobRepository(FakeSessionFactory(FakeSession()))

    assert isinstance(repo, BlobRepository)
    assert not hasattr(repo, "update")
    assert not hasattr(repo, "delete")


async def test_create_persists_blob_model_and_returns_domain_blob() -> None:
    session = FakeSession()
    repo = SQLAlchemyBlobRepository(FakeSessionFactory(session))

    created = await repo.create(_new_blob())

    assert created == Blob(
        id=1,
        sha256=VALID_SHA256,
        byte_size=123,
        content_type="text/plain",
        storage_backend="local",
        storage_key="e3/b0/blob",
        created_at=CREATED_AT,
    )
    assert session.commits == 1
    assert len(session.refreshed) == 1
    added = session.added[0]
    assert isinstance(added, BlobModel)
    assert added.sha256 == VALID_SHA256


async def test_get_by_id_maps_model_to_domain_blob() -> None:
    repo = SQLAlchemyBlobRepository(FakeSessionFactory(FakeSession(get_result=_blob_model())))

    assert await repo.get_by_id(1) == Blob(
        id=1,
        sha256=VALID_SHA256,
        byte_size=123,
        content_type="text/plain",
        storage_backend="local",
        storage_key="e3/b0/blob",
        created_at=CREATED_AT,
    )


async def test_get_by_sha256_maps_model_to_domain_blob() -> None:
    repo = SQLAlchemyBlobRepository(
        FakeSessionFactory(FakeSession(execute_result=_blob_model(sha256=OTHER_SHA256)))
    )

    result = await repo.get_by_sha256(OTHER_SHA256)

    assert result is not None
    assert result.sha256 == OTHER_SHA256


async def test_missing_blob_returns_none() -> None:
    repo = SQLAlchemyBlobRepository(FakeSessionFactory(FakeSession()))

    assert await repo.get_by_id(9999) is None
    assert await repo.get_by_sha256(OTHER_SHA256) is None


async def test_duplicate_sha256_raises_duplicate_blob_error_and_rolls_back() -> None:
    session = FakeSession(commit_error=IntegrityError("insert", {}, Exception("duplicate")))
    repo = SQLAlchemyBlobRepository(FakeSessionFactory(session))

    with pytest.raises(DuplicateBlobError) as exc_info:
        _ = await repo.create(_new_blob())

    assert exc_info.value.sha256 == VALID_SHA256
    assert session.rollbacks == 1
