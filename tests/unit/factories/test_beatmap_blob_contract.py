"""Beatmap file body の blob storage 境界を検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.factories.beatmap import (
    make_beatmap_file_body,
    store_beatmap_file_body_blob,
)

from osu_server.domain.storage.blobs import BlobStorageBackendKind
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.blobs import InMemoryBlobQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.storage.blob_storage import BlobStorageService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from osu_server.infrastructure.storage.interfaces import ByteChunks, StagedBlobWrite


class RecordingBlobBackend:
    """確定済み blob 内容をメモリに記録する fake backend.

    Attributes:
        finalized_content (dict[str, bytes]): storage key ごとの確定済み内容.
    """

    def __init__(self) -> None:
        """空の確定済み内容を持つ fake backend を初期化する."""
        self.finalized_content: dict[str, bytes] = {}

    async def validate_configuration(self) -> None:
        """常に利用可能な backend として設定検証を完了する.

        Returns:
            None: 検証を成功として完了し, 呼び出し側へ値を返さない.
        """
        return

    async def begin_write(self) -> StagedBlobWrite:
        """確定済み内容へ書き込む staged writer を開始する.

        Returns:
            StagedBlobWrite: 書込み内容を蓄積する fake writer.
        """
        return RecordingStagedBlobWrite(self.finalized_content)

    async def open_read(self, storage_key: str) -> ByteChunks:
        """指定 key に確定した内容を非同期 chunk stream として返す.

        Args:
            storage_key (str): 読み出す確定済み blob の key.

        Returns:
            ByteChunks: 内容を一つの chunk で生成する stream.
        """

        async def chunks() -> AsyncIterator[bytes]:
            """確定済み blob 内容を一度だけ生成する.

            Yields:
                bytes: 指定 storage key に対応する内容.
            """
            yield self.finalized_content[storage_key]

        return chunks()

    async def exists(self, storage_key: str) -> bool:
        """指定 storage key の確定済み内容の有無を返す.

        Args:
            storage_key (str): 確認する blob の key.

        Returns:
            bool: key が確定済み内容に存在する場合はTrue.
        """
        return storage_key in self.finalized_content


class RecordingStagedBlobWrite:
    """書込み chunk を蓄積して backend へ確定する fake staged writer.

    Attributes:
        _finalized_content (dict[str, bytes]): finalize 時に更新する backend 内容.
        _written_chunks (list[bytes]): finalize 前に蓄積した chunk.
    """

    _finalized_content: dict[str, bytes]
    _written_chunks: list[bytes]

    def __init__(self, finalized_content: dict[str, bytes]) -> None:
        """共有 backend 内容へ書込みを確定する writer を初期化する.

        Args:
            finalized_content (dict[str, bytes]): finalize 時に更新する共有内容.
        """
        self._finalized_content = finalized_content
        self._written_chunks = []

    async def write(self, chunk: bytes) -> None:
        """確定前の chunk を書込み順に蓄積する.

        Args:
            chunk (bytes): 今回書き込む内容片.

        Returns:
            None: chunk を蓄積し, 呼び出し側へ値を返さない.
        """
        self._written_chunks.append(chunk)

    async def finalize(self, storage_key: str) -> None:
        """蓄積済み chunk を結合して指定 key へ確定する.

        Args:
            storage_key (str): 確定内容を保存する blob の key.

        Returns:
            None: 結合内容を確定し, 呼び出し側へ値を返さない.
        """
        self._finalized_content[storage_key] = b"".join(self._written_chunks)

    async def discard(self) -> None:
        """確定せずに蓄積した chunk を破棄する.

        Returns:
            None: 未確定内容を破棄し, 呼び出し側へ値を返さない.
        """
        self._written_chunks.clear()


def _make_blob_service() -> tuple[BlobStorageService, RecordingBlobBackend]:
    """In-memory repository と recording backend を接続した blob service を作る.

    Returns:
        tuple[BlobStorageService, RecordingBlobBackend]: 検証対象 service と内容観測用 backend.
    """
    backend = RecordingBlobBackend()
    command_state = InMemoryCommandRepositoryState()
    uow_factory = InMemoryUnitOfWorkFactory(command_state)
    service = BlobStorageService(
        blob_query_repo=InMemoryBlobQueryRepository(uow_factory),
        uow_factory=uow_factory,
        backend=backend,
        storage_backend=BlobStorageBackendKind.LOCAL,
    )
    return service, backend


async def test_store_beatmap_file_body_uses_blob_storage_contract() -> None:
    """Beatmap file 保存が内容を blob backend に確定し, attachment が参照だけを持つ契約を検証する.

    Returns:
        None: backend 内容と attachment の観測可能な属性を検証して完了する.
    """
    service, backend = _make_blob_service()
    file_body = make_beatmap_file_body(
        content=b"osu file format v14\n[Metadata]\nTitle: Test\n",
        md5="90ff874e9de3a8f00b7cae9d40c9eb5d",
        original_filename="2000.osu",
    )

    result = await store_beatmap_file_body_blob(
        service,
        file_body,
        beatmap_id=2_000,
        source="mirror",
    )

    assert backend.finalized_content[result.blob.storage_key] == file_body.content
    assert result.attachment.blob_id == result.blob.id
    assert result.attachment.beatmap_id == 2_000
    assert result.attachment.checksum_md5 == file_body.md5
    assert result.attachment.source == "mirror"
    assert result.attachment.original_filename == "2000.osu"
    assert not hasattr(result.attachment, "content")
    assert not hasattr(result.attachment, "body")


async def test_store_beatmap_file_body_deduplicates_through_blob_service() -> None:
    """同一 body の二回保存が同じ blob と attachment 参照へ重複排除される契約を検証する.

    Returns:
        None: 両保存結果の blob と attachment id を検証して完了する.
    """
    service, _backend = _make_blob_service()
    file_body = make_beatmap_file_body(
        content=b"same body",
        md5="841a2d689ad86bd1611447453c22c6fc",
    )

    first = await store_beatmap_file_body_blob(service, file_body)
    second = await store_beatmap_file_body_blob(service, file_body)

    assert first.blob.id == second.blob.id
    assert first.attachment.blob_id == second.attachment.blob_id
