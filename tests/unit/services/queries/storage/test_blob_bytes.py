"""Blob byte reader query boundary tests."""

import pytest

from osu_server.services.queries.storage import (
    BlobByteReaderAdapter,
    BlobBytesUnavailableError,
)


class BackendUnavailableError(FileNotFoundError):
    """Backend 欠落を模した test-only error です。"""


class StaticBlobByteReader:
    """指定された bytes を返す test-only reader です。"""

    read_blob_ids: list[int]

    def __init__(self, content: bytes) -> None:
        self._content: bytes = content
        self.read_blob_ids = []

    async def read_bytes(self, blob_id: int) -> bytes:
        """受け取った blob id を記録して bytes を返します。"""
        self.read_blob_ids.append(blob_id)
        return self._content


class FailingBlobByteReader:
    """指定された例外を送出する test-only reader です。"""

    def __init__(self, error: Exception) -> None:
        self._error: Exception = error

    async def read_bytes(self, blob_id: int) -> bytes:
        """blob id に依存せず指定された例外を送出します。"""
        _ = blob_id
        raise self._error


async def test_blob_byte_reader_adapter_returns_reader_bytes() -> None:
    reader = StaticBlobByteReader(b"ok")
    adapter = BlobByteReaderAdapter(reader)

    result = await adapter.read_bytes(42)

    assert result == b"ok"
    assert reader.read_blob_ids == [42]


async def test_blob_byte_reader_adapter_converts_configured_unavailable_error() -> None:
    backend_error = BackendUnavailableError(
        "backend_detail=SYNTHETIC_PRIVATE_BLOB_LOCATION",
    )
    reader = FailingBlobByteReader(backend_error)
    adapter = BlobByteReaderAdapter(
        reader,
        unavailable_exception_types=(BackendUnavailableError,),
    )

    with pytest.raises(BlobBytesUnavailableError) as exc_info:
        _ = await adapter.read_bytes(123)

    error = exc_info.value
    assert error.blob_id == 123
    assert error.__cause__ is backend_error
    assert vars(error) == {"blob_id": 123}
    assert "123" in str(error)
    assert "SYNTHETIC_PRIVATE_BLOB_LOCATION" not in str(error)
    assert "SYNTHETIC_PRIVATE_BLOB_LOCATION" not in repr(error)


async def test_blob_byte_reader_adapter_preserves_query_unavailable_error() -> None:
    unavailable_error = BlobBytesUnavailableError(blob_id=404)
    adapter = BlobByteReaderAdapter(FailingBlobByteReader(unavailable_error))

    with pytest.raises(BlobBytesUnavailableError) as exc_info:
        _ = await adapter.read_bytes(99)

    assert exc_info.value is unavailable_error


async def test_blob_byte_reader_adapter_preserves_unexpected_exceptions() -> None:
    unexpected_error = RuntimeError("backend_detail=SYNTHETIC_PRIVATE_BLOB_LOCATION")
    adapter = BlobByteReaderAdapter(FailingBlobByteReader(unexpected_error))

    with pytest.raises(RuntimeError) as exc_info:
        _ = await adapter.read_bytes(123)

    assert exc_info.value is unexpected_error
