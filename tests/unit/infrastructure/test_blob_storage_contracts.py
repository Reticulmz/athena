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
    chunks: list[bytes]
    finalized_key: str | None
    discarded: bool

    def __init__(self) -> None:
        self.chunks = []
        self.finalized_key = None
        self.discarded = False

    async def write(self, chunk: bytes) -> None:
        self.chunks.append(chunk)

    async def finalize(self, storage_key: str) -> None:
        self.finalized_key = storage_key

    async def discard(self) -> None:
        self.discarded = True


class ContractOnlyBlobStorageBackend:
    staged: ContractOnlyStagedBlobWrite

    def __init__(self) -> None:
        self.staged = ContractOnlyStagedBlobWrite()

    async def validate_configuration(self) -> None:
        return None

    async def begin_write(self) -> StagedBlobWrite:
        return self.staged

    async def open_read(self, storage_key: str) -> ByteChunks:
        _ = storage_key

        async def chunks() -> AsyncIterator[bytes]:
            yield b"hello"

        return chunks()

    async def exists(self, storage_key: str) -> bool:
        _ = storage_key
        return True


def test_staged_blob_write_contract_accepts_write_finalize_and_discard() -> None:
    staged = ContractOnlyStagedBlobWrite()

    assert isinstance(staged, StagedBlobWrite)
    assert set(signature(StagedBlobWrite.write).parameters) == {"self", "chunk"}
    assert set(signature(StagedBlobWrite.finalize).parameters) == {"self", "storage_key"}
    assert set(signature(StagedBlobWrite.discard).parameters) == {"self"}


def test_blob_storage_backend_contract_exposes_backend_neutral_operations() -> None:
    backend = ContractOnlyBlobStorageBackend()

    assert isinstance(backend, BlobStorageBackend)
    assert set(signature(BlobStorageBackend.validate_configuration).parameters) == {"self"}
    assert set(signature(BlobStorageBackend.begin_write).parameters) == {"self"}
    assert set(signature(BlobStorageBackend.open_read).parameters) == {"self", "storage_key"}
    assert set(signature(BlobStorageBackend.exists).parameters) == {"self", "storage_key"}


def test_backend_contract_does_not_accept_domain_attachment_or_access_fields() -> None:
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
    backend = ContractOnlyBlobStorageBackend()
    chunks = await backend.open_read("sha256/e3/b0/key")

    assert isinstance(chunks, AsyncIterator)
    assert [chunk async for chunk in chunks] == [b"hello"]


def test_storage_error_types_are_specific_and_typed() -> None:
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


def test_storage_package_exports_only_contract_types() -> None:
    assert set(storage.__all__) == {
        "BackendReadError",
        "BackendWriteError",
        "BlobContentMissingError",
        "BlobStorageBackend",
        "BlobStorageConfigurationError",
        "ByteChunks",
        "StagedBlobWrite",
        "UnsupportedBlobStorageBackendError",
    }
