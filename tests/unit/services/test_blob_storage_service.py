"""BlobStorageService の書込み, deduplication, 読込み境界を検証するテスト.

in-memory repository と記録用 storage backend を使う.
metadata と content の失敗経路を分離して検証する.
"""

from __future__ import annotations

import hashlib
from inspect import signature
from typing import TYPE_CHECKING, cast, override

import pytest
from structlog.testing import capture_logs

from osu_server.domain.storage.blobs import BlobDeduplicated, BlobStorageBackendKind, BlobStored
from osu_server.infrastructure.storage.errors import BackendWriteError, BlobContentMissingError
from osu_server.repositories.memory.commands.blobs import InMemoryBlobCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.blobs import InMemoryBlobQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.storage.blob_storage import (
    BlobContentTypeError,
    BlobContentUnavailableError,
    BlobStorageService,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from osu_server.domain.storage.blobs import Blob, NewBlob
    from osu_server.infrastructure.storage.interfaces import ByteChunks, StagedBlobWrite
    from osu_server.repositories.interfaces.queries.blobs import BlobQueryRepository
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork, UnitOfWorkFactory


async def _chunks(*chunks: bytes) -> AsyncIterator[bytes]:
    """指定された byte chunk を入力順で非同期送出する.

    Args:
        *chunks (bytes): stream として送出する byte 列.

    Yields:
        bytes: 呼出し側が渡した各 chunk.
    """
    for chunk in chunks:
        yield chunk


def _sha256_storage_key(content: bytes) -> str:
    """Content の SHA-256 digest から storage key を組み立てる.

    Args:
        content (bytes): key を導出する byte 列.

    Returns:
        str: sha256 prefix と digest shard を含む deterministic storage key.
    """
    digest = hashlib.sha256(content).hexdigest()
    return f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"


class RecordingBackend:
    """blob storage backend の操作と content を記録する test double.

    Attributes:
        staged_writes (list[RecordingStagedWrite]): 開始した staged write の履歴.
        finalized_content (dict[str, bytes]): finalize 済み storage key と content の対応.
        fail_writes (bool): write 時に BackendWriteError を送出するかどうか.
        fail_finalize (bool): finalize 時に BackendWriteError を送出するかどうか.
        missing_reads (set[str]): content missing として扱う storage key.
    """

    staged_writes: list[RecordingStagedWrite]
    finalized_content: dict[str, bytes]
    fail_writes: bool
    fail_finalize: bool
    missing_reads: set[str]

    def __init__(
        self,
        *,
        fail_writes: bool = False,
        fail_finalize: bool = False,
        missing_reads: set[str] | None = None,
    ) -> None:
        """失敗条件を指定して記録用 backend を初期化する.

        Args:
            fail_writes (bool): staged write を失敗させるかどうか.
            fail_finalize (bool): staged finalize を失敗させるかどうか.
            missing_reads (set[str] | None): read 時に missing とする storage key.
                None は空集合.
        """
        self.staged_writes = []
        self.finalized_content = {}
        self.fail_writes = fail_writes
        self.fail_finalize = fail_finalize
        self.missing_reads = missing_reads or set()

    async def validate_configuration(self) -> None:
        """Test backend の設定が常に有効であることを報告する.

        Returns:
            None: 外部設定を検証せず正常終了する.
        """
        return

    async def begin_write(self) -> StagedBlobWrite:
        """新しい staged write を作成して履歴へ記録する.

        Returns:
            StagedBlobWrite: backend の失敗条件を共有する staged write.
        """
        staged = RecordingStagedWrite(
            finalized_content=self.finalized_content,
            fail_writes=self.fail_writes,
            fail_finalize=self.fail_finalize,
        )
        self.staged_writes.append(staged)
        return staged

    async def open_read(self, storage_key: str) -> ByteChunks:
        """Finalize 済み content の非同期 chunk stream を開く.

        Args:
            storage_key (str): 読み込む finalized content の key.

        Returns:
            ByteChunks: content 全体を1 chunkで返す非同期 stream.

        Raises:
            BlobContentMissingError: key が missing_reads に含まれる場合.
        """
        if storage_key in self.missing_reads:
            raise BlobContentMissingError(storage_key)

        async def chunks() -> AsyncIterator[bytes]:
            """指定 key に保存した content を1回送出する.

            Yields:
                bytes: storage key に対応する finalized content.
            """
            yield self.finalized_content[storage_key]

        return chunks()

    async def exists(self, storage_key: str) -> bool:
        """Storage key に finalize 済み content があるかを返す.

        Args:
            storage_key (str): 存在確認する key.

        Returns:
            bool: finalized_content に key が存在する場合は True.
        """
        return storage_key in self.finalized_content


class RecordingStagedWrite:
    """staged blob write の content と cleanup 状態を記録する test double.

    Attributes:
        chunks (list[bytes]): write 済み content chunk.
        discarded (bool): discard が呼び出されたかどうか.
        finalized_key (str | None): finalize 済み key. 未 finalize 時は None.
    """

    _finalized_content: dict[str, bytes]
    _fail_writes: bool
    _fail_finalize: bool
    chunks: list[bytes]
    discarded: bool
    finalized_key: str | None

    def __init__(
        self,
        *,
        finalized_content: dict[str, bytes],
        fail_writes: bool,
        fail_finalize: bool,
    ) -> None:
        """Finalized content の共有先と失敗条件を設定する.

        Args:
            finalized_content (dict[str, bytes]): finalize 結果を書き込む共有 mapping.
            fail_writes (bool): write を失敗させるかどうか.
            fail_finalize (bool): finalize を失敗させるかどうか.
        """
        self._finalized_content = finalized_content
        self._fail_writes = fail_writes
        self._fail_finalize = fail_finalize
        self.chunks = []
        self.discarded = False
        self.finalized_key = None

    async def write(self, chunk: bytes) -> None:
        """Chunk を staged content に追加する.

        Args:
            chunk (bytes): 追加する content chunk.

        Returns:
            None: chunk を記録して完了する.

        Raises:
            BackendWriteError: fail_writes が True の場合.
        """
        if self._fail_writes:
            raise BackendWriteError("forced staged write failure")
        self.chunks.append(chunk)

    async def finalize(self, storage_key: str) -> None:
        """Staged chunk を結合して finalized content として保存する.

        Args:
            storage_key (str): finalized content に割り当てる key.

        Returns:
            None: content と finalized key を記録して完了する.

        Raises:
            BackendWriteError: fail_finalize が True の場合.
        """
        if self._fail_finalize:
            raise BackendWriteError("forced finalize failure")
        self.finalized_key = storage_key
        self._finalized_content[storage_key] = b"".join(self.chunks)

    async def discard(self) -> None:
        """Staged write が破棄されたことを記録する.

        Returns:
            None: discarded flag を True に設定して完了する.
        """
        self.discarded = True


class FailingCreateBlobCommandRepository(InMemoryBlobCommandRepository):
    """metadata create を強制失敗させる in-memory blob command repository."""

    @override
    async def create(self, blob: NewBlob) -> Blob:
        """Metadata create 失敗を再現する.

        Args:
            blob (NewBlob): 作成対象. 失敗再現のため使用しない.

        Returns:
            Blob: 正常時は返る想定だが常に例外を送出するため返らない.

        Raises:
            RuntimeError: metadata create failure を再現するため常に送出する.
        """
        _ = blob
        raise RuntimeError("forced metadata create failure")


class FailingCreateUnitOfWork:
    """blob metadata create だけを失敗させる UnitOfWork test double.

    Attributes:
        blobs (FailingCreateBlobCommandRepository): 常に create を失敗させる command repository.
    """

    blobs: FailingCreateBlobCommandRepository

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """失敗 repository の backing state を設定する.

        Args:
            state (InMemoryCommandRepositoryState): repository が参照する in-memory state.
        """
        self.blobs = FailingCreateBlobCommandRepository(state)

    async def __aenter__(self) -> UnitOfWork:
        """Context manager として利用する UnitOfWork 自身を返す.

        Returns:
            UnitOfWork: protocol に cast したこの test double.
        """
        return cast("UnitOfWork", cast("object", self))

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """Transaction 終了時に rollback 等を行わず終了する.

        Args:
            exc_type (type[BaseException] | None): 発生した例外型. 失敗再現では保持しない.
            _exc (BaseException | None): 発生した例外. 使用しない.
            _traceback (TracebackType | None): 発生した traceback. 使用しない.

        Returns:
            None: 例外を抑制せず context manager を終了する.
        """
        _ = exc_type

    async def commit(self) -> None:
        """Commit を no-op として受け付ける.

        Returns:
            None: 永続化を変更せず完了する.
        """
        return

    async def rollback(self) -> None:
        """Rollback を no-op として受け付ける.

        Returns:
            None: 永続化を変更せず完了する.
        """
        return


class FailingCreateUnitOfWorkFactory:
    """metadata create failure 用 UnitOfWork を生成する factory."""

    _state: InMemoryCommandRepositoryState

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """Factory が渡す UnitOfWork の backing state を設定する.

        Args:
            state (InMemoryCommandRepositoryState): test double が共有する command state.
        """
        self._state = state

    def __call__(self) -> AbstractAsyncContextManager[UnitOfWork]:
        """Metadata create が失敗する非同期 context manager を生成する.

        Returns:
            AbstractAsyncContextManager[UnitOfWork]: 新しい failing UnitOfWork.
        """
        return FailingCreateUnitOfWork(self._state)


def _make_service(
    *,
    uow_factory: UnitOfWorkFactory | None = None,
    query_repo: BlobQueryRepository | None = None,
    backend: RecordingBackend | None = None,
) -> tuple[BlobStorageService, BlobQueryRepository, RecordingBackend]:
    """BlobStorageService と差し替え可能な in-memory 依存を構築する.

    Args:
        uow_factory (UnitOfWorkFactory | None): metadata command 用 factory.
            None は既定 factory.
        query_repo (BlobQueryRepository | None): metadata read 用 repository.
            None は既定 repository.
        backend (RecordingBackend | None): content backend. None は記録用既定 backend.

    Returns:
        tuple[BlobStorageService, BlobQueryRepository, RecordingBackend]:
            service, query repository, backend の組.
    """
    command_state = InMemoryCommandRepositoryState()
    selected_uow_factory = uow_factory or InMemoryUnitOfWorkFactory(command_state)
    selected_query_repo = query_repo or InMemoryBlobQueryRepository(
        InMemoryUnitOfWorkFactory(command_state)
    )
    selected_backend = backend or RecordingBackend()
    service = BlobStorageService(
        blob_query_repo=selected_query_repo,
        uow_factory=selected_uow_factory,
        backend=selected_backend,
        storage_backend=BlobStorageBackendKind.LOCAL,
    )
    return service, selected_query_repo, selected_backend


async def test_put_stream_stores_new_blob_with_integrity_metadata() -> None:
    """新規 stream が digest, size, storage key を持つ blob として保存されることを検証する.

    Returns:
        None: metadata と finalized content の一致を検証して完了する.
    """
    service, repo, backend = _make_service()
    content = b"hello blob storage"

    result = await service.put_stream(
        _chunks(b"hello ", b"blob ", b"storage"),
        content_type="text/plain",
    )

    assert isinstance(result, BlobStored)
    assert result.blob.sha256 == hashlib.sha256(content).hexdigest()
    assert result.blob.byte_size == len(content)
    assert result.blob.content_type == "text/plain"
    assert result.blob.storage_backend == "local"
    assert result.blob.storage_key == _sha256_storage_key(content)
    assert backend.finalized_content[result.blob.storage_key] == content
    assert await repo.get_by_sha256(result.blob.sha256) == result.blob


async def test_put_stream_accepts_explicit_octet_stream_content_type() -> None:
    """application/octet-stream を明示した stream が保存できることを検証する.

    Returns:
        None: 保存結果の content type を検証して完了する.
    """
    service, _repo, _backend = _make_service()

    result = await service.put_stream(
        _chunks(b"unknown binary"),
        content_type="application/octet-stream",
    )

    assert isinstance(result, BlobStored)
    assert result.blob.content_type == "application/octet-stream"


async def test_put_stream_returns_existing_blob_for_duplicate_content() -> None:
    """同一 content の再投入が既存 blob を返し staged write を破棄することを検証する.

    Returns:
        None: deduplication 結果, cleanup, security log を検証して完了する.
    """
    service, _repo, backend = _make_service()
    content = b"duplicate content"
    stored = await service.put_stream(_chunks(content), content_type="text/plain")
    assert isinstance(stored, BlobStored)

    with capture_logs() as logs:
        duplicate = await service.put_stream(
            _chunks(b"duplicate ", b"content"),
            content_type="application/octet-stream",
        )

    assert isinstance(duplicate, BlobDeduplicated)
    assert duplicate.blob == stored.blob
    assert len(backend.staged_writes) == 2
    assert backend.staged_writes[1].discarded is True
    assert backend.staged_writes[1].finalized_key is None
    assert backend.finalized_content == {stored.blob.storage_key: content}
    events = [event for event in logs if event["event"] == "blob_write_deduplicated"]
    assert len(events) == 1
    assert events[0]["sha256"] == stored.blob.sha256
    assert events[0]["byte_size"] == len(content)
    assert b"duplicate content".decode() not in repr(logs)


async def test_put_bytes_matches_stream_identity_for_same_content() -> None:
    """put_bytes と put_stream が同一 content identity を共有することを検証する.

    Returns:
        None: helper 経由の結果が既存 blob を返すことを検証して完了する.
    """
    service, _repo, backend = _make_service()
    content = b"same identity through helper and stream"
    streamed = await service.put_stream(
        _chunks(b"same identity ", b"through helper ", b"and stream"),
        content_type="text/plain",
    )
    assert isinstance(streamed, BlobStored)

    helper = await service.put_bytes(content, content_type="application/octet-stream")

    assert isinstance(helper, BlobDeduplicated)
    assert helper.blob == streamed.blob
    assert helper.blob.sha256 == hashlib.sha256(content).hexdigest()
    assert helper.blob.byte_size == len(content)
    assert helper.blob.content_type == "text/plain"
    assert backend.finalized_content == {streamed.blob.storage_key: content}


async def test_put_stream_rejects_missing_content_type_before_staging() -> None:
    """空の content type が staging 前に拒否されることを検証する.

    Returns:
        None: BlobContentTypeError と staged write 非作成を検証して完了する.
    """
    service, _repo, backend = _make_service()

    with pytest.raises(BlobContentTypeError):
        _ = await service.put_stream(_chunks(b"content"), content_type="")

    assert backend.staged_writes == []


async def test_put_stream_discards_staging_and_logs_when_write_fails() -> None:
    """Staged write failure 時に cleanup, metadata 非作成, sanitized log を検証する.

    Returns:
        None: BackendWriteError の再送出と失敗後状態を検証して完了する.
    """
    backend = RecordingBackend(fail_writes=True)
    service, repo, _backend = _make_service(backend=backend)

    with (
        capture_logs() as logs,
        pytest.raises(BackendWriteError, match="forced staged write failure"),
    ):
        _ = await service.put_stream(_chunks(b"failed content"), content_type="text/plain")

    assert len(backend.staged_writes) == 1
    assert backend.staged_writes[0].discarded is True
    assert await repo.get_by_id(1) is None
    events = [event for event in logs if event["event"] == "blob_write_failed"]
    assert len(events) == 1
    assert events[0]["reason"] == "BackendWriteError"
    assert events[0]["byte_size"] == len(b"failed content")
    assert "failed content" not in repr(logs)


async def test_put_stream_discards_staging_and_logs_when_finalize_fails() -> None:
    """Finalize failure 時に staging が破棄され content が保存されないことを検証する.

    Returns:
        None: BackendWriteError と failure log を検証して完了する.
    """
    backend = RecordingBackend(fail_finalize=True)
    service, repo, _backend = _make_service(backend=backend)

    with (
        capture_logs() as logs,
        pytest.raises(BackendWriteError, match="forced finalize failure"),
    ):
        _ = await service.put_stream(_chunks(b"failed finalize"), content_type="text/plain")

    assert len(backend.staged_writes) == 1
    assert backend.staged_writes[0].discarded is True
    assert backend.finalized_content == {}
    assert await repo.get_by_id(1) is None
    events = [event for event in logs if event["event"] == "blob_write_failed"]
    assert len(events) == 1
    assert events[0]["reason"] == "BackendWriteError"


async def test_put_stream_does_not_discard_after_finalize_when_metadata_create_fails() -> None:
    """Metadata create failure 後に finalized content を破棄しないことを検証する.

    Returns:
        None: finalize 済み content, discard 状態, failure reason を検証して完了する.
    """
    command_state = InMemoryCommandRepositoryState()
    backend = RecordingBackend()
    service, _repo, _backend = _make_service(
        uow_factory=FailingCreateUnitOfWorkFactory(command_state),
        query_repo=InMemoryBlobQueryRepository(InMemoryUnitOfWorkFactory(command_state)),
        backend=backend,
    )
    content = b"metadata create failure"

    with (
        capture_logs() as logs,
        pytest.raises(RuntimeError, match="failed to create blob metadata"),
    ):
        _ = await service.put_stream(_chunks(content), content_type="text/plain")

    assert len(backend.staged_writes) == 1
    assert backend.staged_writes[0].finalized_key == _sha256_storage_key(content)
    assert backend.staged_writes[0].discarded is False
    assert backend.finalized_content == {_sha256_storage_key(content): content}
    events = [event for event in logs if event["event"] == "blob_write_failed"]
    assert len(events) == 1
    assert events[0]["reason"] == "BlobStorageWriteError"


async def test_stream_read_returns_backend_chunks_for_existing_blob() -> None:
    """既存 blob の stream_read と read_bytes が backend content を返すことを検証する.

    Returns:
        None: 非同期 stream と helper の content 一致を検証して完了する.
    """
    service, _repo, _backend = _make_service()
    stored = await service.put_bytes(b"read me", content_type="text/plain")
    assert isinstance(stored, BlobStored)

    chunks = await service.stream_read(stored.blob.id)

    assert b"".join([chunk async for chunk in chunks]) == b"read me"
    assert await service.read_bytes(stored.blob.id) == b"read me"


async def test_stream_read_does_not_rehash_backend_content() -> None:
    """Read path が backend content を再 hash せず metadata identity を信頼することを検証する.

    Returns:
        None: read content と保存済み SHA-256 が独立であることを検証して完了する.
    """
    service, _repo, backend = _make_service()
    stored = await service.put_bytes(
        b"metadata integrity is write-time",
        content_type="text/plain",
    )
    assert isinstance(stored, BlobStored)
    backend.finalized_content[stored.blob.storage_key] = b"backend stream is trusted on read"

    chunks = await service.stream_read(stored.blob.id)

    assert b"".join([chunk async for chunk in chunks]) == b"backend stream is trusted on read"
    assert stored.blob.sha256 == hashlib.sha256(b"metadata integrity is write-time").hexdigest()


async def test_stream_read_reports_missing_blob_metadata_as_unavailable() -> None:
    """存在しない blob metadata が content unavailable として公開されることを検証する.

    Returns:
        None: BlobContentUnavailableError と metadata missing log を検証して完了する.
    """
    service, _repo, _backend = _make_service()

    with (
        capture_logs() as logs,
        pytest.raises(BlobContentUnavailableError),
    ):
        _ = await service.stream_read(404)

    events = [event for event in logs if event["event"] == "blob_read_failed"]
    assert len(events) == 1
    assert events[0]["blob_id"] == 404
    assert events[0]["reason"] == "BlobMetadataMissing"


async def test_stream_read_reports_missing_backend_content_as_unavailable() -> None:
    """存在しない backend content が content unavailable として公開されることを検証する.

    Returns:
        None: BlobContentUnavailableError と sanitized failure log を検証して完了する.
    """
    backend = RecordingBackend()
    service, _repo, _backend = _make_service(backend=backend)
    stored = await service.put_bytes(b"metadata without content", content_type="text/plain")
    assert isinstance(stored, BlobStored)
    backend.missing_reads.add(stored.blob.storage_key)

    with (
        capture_logs() as logs,
        pytest.raises(BlobContentUnavailableError),
    ):
        _ = await service.stream_read(stored.blob.id)

    events = [event for event in logs if event["event"] == "blob_read_failed"]
    assert len(events) == 1
    assert events[0]["reason"] == "BlobContentMissingError"
    assert "metadata without content" not in repr(logs)


def test_blob_storage_service_surface_excludes_lifecycle_and_attachment_operations() -> None:
    """BlobStorageService が content I/O だけを公開する境界を検証する.

    Returns:
        None: lifecycle と attachment 操作が service surface にないことを検証して完了する.
    """
    public_methods = {
        "put_bytes",
        "put_stream",
        "read_bytes",
        "stream_read",
    }

    assert public_methods == {"put_bytes", "put_stream", "read_bytes", "stream_read"}
    for method_name in public_methods:
        assert hasattr(BlobStorageService, method_name)
    assert not hasattr(BlobStorageService, "delete")
    assert not hasattr(BlobStorageService, "discard")
    assert not hasattr(BlobStorageService, "garbage_collect")
    assert not hasattr(BlobStorageService, "attach")
    assert not hasattr(BlobStorageService, "create_attachment")
    assert not hasattr(BlobStorageService, "authorize")


def test_blob_storage_service_read_contract_uses_trusted_blob_identity_only() -> None:
    """Read API が blob ID だけを受け取る trusted identity 契約を検証する.

    Returns:
        None: filename や authorization input が read signature にないことを検証して完了する.
    """
    stream_parameters = set(signature(BlobStorageService.stream_read).parameters)
    read_parameters = set(signature(BlobStorageService.read_bytes).parameters)

    assert stream_parameters == {"self", "blob_id"}
    assert read_parameters == {"self", "blob_id"}
    for parameters in (stream_parameters, read_parameters):
        assert "filename" not in parameters
        assert "uploader_id" not in parameters
        assert "owner_id" not in parameters
        assert "access_policy" not in parameters
        assert "authorized_user_id" not in parameters
