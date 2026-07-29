"""Blob storage Protocolとtyped error surfaceの境界契約を検証する."""

from __future__ import annotations

from collections.abc import AsyncIterator
from inspect import signature

from osu_server.infrastructure import storage
from osu_server.infrastructure.storage import (
    BackendReadError,
    BackendWriteError,
    BlobContentMissingError,
    BlobStorageBackend,
    BlobStorageConfigurationError,
    ByteChunks,
    StagedBlobWrite,
    UnsupportedBlobStorageBackendError,
)


class ContractOnlyStagedBlobWrite:
    """StagedBlobWrite structural contractだけを実装するin-memory fakeを表す.

    Attributes:
        chunks (list[bytes]): writeで受け取ったchunkの順序付き記録.
        finalized_key (str | None): finalizeで指定されたstorage key. 未finalize時はNone.
        discarded (bool): discardが呼ばれたかを示すflag.
    """

    chunks: list[bytes]
    finalized_key: str | None
    discarded: bool

    def __init__(self) -> None:
        """空のchunk記録と未完了stateでstaged write fakeを初期化する."""
        self.chunks = []
        self.finalized_key = None
        self.discarded = False

    async def write(self, chunk: bytes) -> None:
        """受け取ったchunkを順序を保って記録する.

        Args:
            chunk (bytes): staged writeへ追加するcontent fragment.

        Returns:
            None: chunkを記録して完了し値を返さない.
        """
        self.chunks.append(chunk)

    async def finalize(self, storage_key: str) -> None:
        """Finalized storage keyを記録する.

        Args:
            storage_key (str): staged contentへ割り当てるfinal storage key.

        Returns:
            None: final keyを記録して完了し値を返さない.
        """
        self.finalized_key = storage_key

    async def discard(self) -> None:
        """Discardが要求されたstateを記録する.

        Returns:
            None: discard flagを設定して完了し値を返さない.
        """
        self.discarded = True


class ContractOnlyBlobStorageBackend:
    """BlobStorageBackend structural contractだけを実装する固定response fakeを表す.

    Attributes:
        staged (ContractOnlyStagedBlobWrite): begin_writeが返す再利用可能なstaged write fake.
    """

    staged: ContractOnlyStagedBlobWrite

    def __init__(self) -> None:
        """空のstaged write fakeを持つbackend fakeを初期化する."""
        self.staged = ContractOnlyStagedBlobWrite()

    async def validate_configuration(self) -> None:
        """常に有効なtest configurationとして検証を完了する.

        Returns:
            None: configurationを変更せず検証を完了する.
        """
        return

    async def begin_write(self) -> StagedBlobWrite:
        """事前生成したstaged write fakeを返す.

        Returns:
            StagedBlobWrite: contract検証に使うin-memory staged writer.
        """
        return self.staged

    async def open_read(self, storage_key: str) -> ByteChunks:
        """Storage keyにかかわらず固定のbyte streamを返す.

        Args:
            storage_key (str): contract上受け付けるcontent識別子.

        Returns:
            ByteChunks: hello bytesを1回yieldするasync iterator.
        """
        _ = storage_key

        async def chunks() -> AsyncIterator[bytes]:
            """固定のcontent chunkを1回yieldする.

            Yields:
                bytes: backend read contractを表すhello content.
            """
            yield b"hello"

        return chunks()

    async def exists(self, storage_key: str) -> bool:
        """Storage keyにかかわらずcontentが存在すると返す.

        Args:
            storage_key (str): contract上受け付けるcontent識別子.

        Returns:
            bool: fake backendが常に返すTrue.
        """
        _ = storage_key
        return True


def test_staged_blob_write_contract_accepts_write_finalize_and_discard() -> None:
    """StagedBlobWriteが3操作を持つstructural Protocolである契約を検証する.

    各methodを実装するfakeを生成してProtocolとsignatureを検査する.
    writeとfinalizeとdiscardが期待するparameterだけを公開することを確認する.

    Returns:
        None: staged write contractを検証して完了し値を返さない.
    """
    staged = ContractOnlyStagedBlobWrite()

    assert isinstance(staged, StagedBlobWrite)
    assert set(signature(StagedBlobWrite.write).parameters) == {"self", "chunk"}
    assert set(signature(StagedBlobWrite.finalize).parameters) == {"self", "storage_key"}
    assert set(signature(StagedBlobWrite.discard).parameters) == {"self"}


def test_blob_storage_backend_contract_exposes_backend_neutral_operations() -> None:
    """BlobStorageBackendがbackend非依存の4操作を公開する契約を検証する.

    全操作を実装するfakeを生成してProtocolとsignatureを検査する.
    validateとbeginとreadとexistsが必要なparameterだけを公開することを確認する.

    Returns:
        None: backend Protocol surfaceを検証して完了し値を返さない.
    """
    backend = ContractOnlyBlobStorageBackend()

    assert isinstance(backend, BlobStorageBackend)
    assert set(signature(BlobStorageBackend.validate_configuration).parameters) == {"self"}
    assert set(signature(BlobStorageBackend.begin_write).parameters) == {"self"}
    assert set(signature(BlobStorageBackend.open_read).parameters) == {"self", "storage_key"}
    assert set(signature(BlobStorageBackend.exists).parameters) == {"self", "storage_key"}


def test_backend_contract_does_not_accept_domain_attachment_or_access_fields() -> None:
    """Blob storage contractがdomain attachmentやaccess fieldを受け取らない契約を検証する.

    Finalizeとreadとexistsのsignatureを走査する.
    filenameとownerとauthorization関連parameterが存在しないことを確認する.

    Returns:
        None: backend境界のprimitive-only inputを検証して完了し値を返さない.
    """
    for method in (
        StagedBlobWrite.finalize,
        BlobStorageBackend.open_read,
        BlobStorageBackend.exists,
    ):
        parameters = set(signature(method).parameters)

        assert "filename" not in parameters
        assert "original_filename" not in parameters
        assert "uploader_id" not in parameters
        assert "owner_id" not in parameters
        assert "access_policy" not in parameters
        assert "authorized_user_id" not in parameters


async def test_backend_contract_streams_byte_chunks() -> None:
    """BlobStorageBackendのreadがByteChunksをstreamする契約を検証する.

    固定response fakeでstorage keyをopen_readする.
    async iteratorがhello bytesを順序どおりyieldすることを確認する.

    Returns:
        None: backend read stream contractを検証して完了し値を返さない.
    """
    backend = ContractOnlyBlobStorageBackend()
    chunks = await backend.open_read("sha256/e3/b0/key")

    assert isinstance(chunks, AsyncIterator)
    assert [chunk async for chunk in chunks] == [b"hello"]


def test_storage_error_types_are_specific_and_typed() -> None:
    """Storage errorがcategory固有のcontextとmessageを保持する契約を検証する.

    Configurationとunsupportedとmissingとreadとwrite errorを生成する.
    inheritanceとstorage keyとbackend名と文字列表現が入力を保持することを確認する.

    Returns:
        None: typed storage error surfaceを検証して完了し値を返さない.
    """
    config_error = BlobStorageConfigurationError("root is not writable")
    unsupported_error = UnsupportedBlobStorageBackendError("s3")
    missing_error = BlobContentMissingError("sha256/e3/b0/key")
    read_error = BackendReadError("sha256/e3/b0/key")
    write_error = BackendWriteError("local write failed")

    assert isinstance(unsupported_error, BlobStorageConfigurationError)
    assert unsupported_error.backend == "s3"
    assert missing_error.storage_key == "sha256/e3/b0/key"
    assert read_error.storage_key == "sha256/e3/b0/key"
    assert str(config_error) == "root is not writable"
    assert str(write_error) == "local write failed"


def test_storage_package_exports_contract_types_errors_and_factory() -> None:
    """Storage packageが契約型とerrorとfactoryだけをexportする契約を検証する.

    packageの__all__集合を読み取る.
    public surfaceが想定した9個のsymbolと完全一致することを確認する.

    Returns:
        None: storage package export contractを検証して完了し値を返さない.
    """
    assert set(storage.__all__) == {
        "BackendReadError",
        "BackendWriteError",
        "BlobContentMissingError",
        "BlobStorageBackend",
        "BlobStorageConfigurationError",
        "ByteChunks",
        "StagedBlobWrite",
        "UnsupportedBlobStorageBackendError",
        "create_blob_storage_backend",
    }
