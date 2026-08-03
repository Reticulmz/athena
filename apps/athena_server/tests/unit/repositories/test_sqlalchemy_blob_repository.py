"""SQLAlchemy blob command repositoryのmappingとerror処理を検証する."""

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
    """scalar lookup結果を返すSQLAlchemy resultの最小fakeを表す.

    Attributes:
        _blob (BlobModel | None): scalar lookupで返すmodelまたは欠損値.
    """

    _blob: BlobModel | None

    def __init__(self, blob: BlobModel | None) -> None:
        """Scalar lookup結果として返すblob modelを初期化する.

        Args:
            blob (BlobModel | None): scalar lookupで返すmodelまたはNone.
        """
        self._blob = blob

    def scalar_one_or_none(self) -> BlobModel | None:
        """保存したscalar lookup結果を返す.

        Returns:
            BlobModel | None: 初期化時に設定したmodelまたはNone.
        """
        return self._blob


class FakeSession(AbstractAsyncContextManager["FakeSession"]):
    """SQLAlchemy blob repositoryが使うAsyncSession操作を再現するfake session.

    Attributes:
        added (list[object]): addで受け取ったinstanceの順序付き記録.
        flushes (int): flushが成功した回数.
        refreshed (list[object]): refreshで更新したinstanceの記録.
        get_result (BlobModel | None): getが返すblob modelまたはNone.
        execute_result (BlobModel | None): executeのscalar結果として返すmodelまたはNone.
        flush_error (IntegrityError | None): flush時に送出するdatabase integrity errorまたはNone.
    """

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
        """必要なlookup結果とflush failureを持つfake sessionを初期化する.

        Args:
            get_result (BlobModel | None): ID lookupで返すmodelまたはNone.
            execute_result (BlobModel | None): SHA-256 lookupで返すmodelまたはNone.
            flush_error (IntegrityError | None): flush時に送出するerrorまたはNone.
        """
        self.added = []
        self.flushes = 0
        self.refreshed = []
        self.get_result = get_result
        self.execute_result = execute_result
        self.flush_error = flush_error

    @override
    async def __aenter__(self) -> FakeSession:
        """Context manager内で利用するこのfake sessionを返す.

        Returns:
            FakeSession: context内で利用する同一session instance.
        """
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Context終了時のexception情報を消費して追加処理なしで完了する.

        Args:
            exc_type (type[BaseException] | None): context内で送出されたexception型またはNone.
            exc (BaseException | None): context内で送出されたexception instanceまたはNone.
            traceback (TracebackType | None): exception tracebackまたはNone.

        Returns:
            None: transaction cleanupを行わずにcontext終了処理を完了する.
        """
        _ = exc_type
        _ = exc
        _ = traceback

    async def get(self, model_type: type[BlobModel], blob_id: int) -> BlobModel | None:
        """ID lookup用に設定済みのmodel結果を返す.

        Args:
            model_type (type[BlobModel]): lookup対象model型.
            blob_id (int): lookup対象blob識別子.

        Returns:
            BlobModel | None: 初期化時に設定したget結果.
        """
        _ = model_type
        _ = blob_id
        return self.get_result

    async def execute(self, statement: Executable) -> BlobResult:
        """Query実行結果として設定済みmodelを包むscalar resultを返す.

        Args:
            statement (Executable): repositoryが発行したSQLAlchemy statement.

        Returns:
            BlobResult: execute_resultを返すscalar lookup result.
        """
        _ = statement
        return BlobResult(self.execute_result)

    def add(self, instance: object) -> None:
        """永続化対象instanceを追加記録へ積む.

        Args:
            instance (object): sessionへ追加するORM instance.

        Returns:
            None: instanceを追加記録へ格納して完了する.
        """
        self.added.append(instance)

    async def flush(self) -> None:
        """設定済みerrorを送出するか成功したflush回数を増やす.

        Returns:
            None: 成功時にflush回数を1増やして完了する.

        Raises:
            IntegrityError: 初期化時にflush_errorが設定されている場合.
        """
        if self.flush_error is not None:
            raise self.flush_error
        self.flushes += 1

    async def refresh(self, instance: object) -> None:
        """BlobModelへdatabaseが割り当てるIDと作成時刻を設定する.

        Args:
            instance (object): refresh対象として渡されたBlobModel instance.

        Returns:
            None: IDと作成時刻を設定してrefresh記録へ追加する.

        Raises:
            AssertionError: instanceがBlobModelではない場合.
        """
        assert isinstance(instance, BlobModel)
        instance.id = 1
        instance.created_at = CREATED_AT
        self.refreshed.append(instance)


def _new_blob(*, sha256: str = VALID_SHA256) -> NewBlob:
    """SQLAlchemy create testへ渡す既定blob metadataを作成する.

    Args:
        sha256 (str): 作成対象blobの64文字SHA-256値.

    Returns:
        NewBlob: create操作へ渡す検証済みblob metadata.
    """
    return NewBlob(
        sha256=sha256,
        byte_size=123,
        content_type="text/plain",
        storage_backend=BlobStorageBackendKind.LOCAL,
        storage_key="e3/b0/blob",
    )


def _blob_model(*, id: int = 1, sha256: str = VALID_SHA256) -> BlobModel:  # noqa: A002
    """SQLAlchemy lookupが返すBlobModelを作成する.

    Args:
        id (int): modelへ設定するdatabase identity.
        sha256 (str): modelへ設定する64文字SHA-256値.

    Returns:
        BlobModel: repositoryがdomain BlobへmapするORM model.
    """
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
    """FakeSessionを受け取るSQLAlchemy blob command repositoryを作成する.

    Args:
        session (FakeSession): AsyncSessionとして振る舞うtest double.

    Returns:
        SQLAlchemyBlobCommandRepository: 指定fake sessionを使用するrepository.
    """
    return SQLAlchemyBlobCommandRepository(cast("AsyncSession", cast("object", session)))


def test_sqlalchemy_blob_repository_satisfies_contract() -> None:
    """SQLAlchemy blob repositoryが必要なcommand contractだけを満たすことを検証する.

    Returns:
        None: runtime Protocol conformanceと禁止操作の不在を検証して完了する.
    """
    repo = _repo(FakeSession())

    assert isinstance(repo, BlobCommandRepository)
    assert not hasattr(repo, "update")
    assert not hasattr(repo, "delete")


async def test_create_persists_blob_model_and_returns_domain_blob() -> None:
    """CreateがORM modelを保存してdomain Blobへmapすることを検証する.

    Returns:
        None: 保存結果とflush/refreshおよび追加ORM modelを検証して完了する.
    """
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
    """ID lookupがBlobModelをdomain Blobへmapすることを検証する.

    Returns:
        None: lookup結果の全domain fieldを検証して完了する.
    """
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
    """SHA-256 lookupがBlobModelをdomain Blobへmapすることを検証する.

    Returns:
        None: query結果の存在とSHA-256値を検証して完了する.
    """
    repo = _repo(FakeSession(execute_result=_blob_model(sha256=OTHER_SHA256)))

    result = await repo.get_by_sha256(OTHER_SHA256)

    assert result is not None
    assert result.sha256 == OTHER_SHA256


async def test_missing_blob_returns_none() -> None:
    """IDとSHA-256 lookupが欠損blobでNoneを返すことを検証する.

    Returns:
        None: 両lookup経路の欠損結果を検証して完了する.
    """
    repo = _repo(FakeSession())

    assert await repo.get_by_id(9999) is None
    assert await repo.get_by_sha256(OTHER_SHA256) is None


async def test_duplicate_sha256_raises_duplicate_blob_error() -> None:
    """Create時のunique constraint違反がDuplicateBlobErrorへ変換されることを検証する.

    Returns:
        None: errorが競合SHA-256を保持しflush成功回数を増やさないことを検証して完了する.
    """
    session = FakeSession(flush_error=IntegrityError("insert", {}, Exception("duplicate")))
    repo = _repo(session)

    with pytest.raises(DuplicateBlobError) as exc_info:
        _ = await repo.create(_new_blob())

    assert exc_info.value.sha256 == VALID_SHA256
    assert session.flushes == 0
