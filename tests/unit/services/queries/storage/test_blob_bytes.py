"""blob byte reader query boundaryのunit testを定義する."""

import pytest

from osu_server.services.queries.storage import (
    BlobByteReaderAdapter,
    BlobBytesUnavailableError,
)


class BackendUnavailableError(FileNotFoundError):
    """backendのunavailable状態を模したtest-only errorを表す."""


class StaticBlobByteReader:
    """指定されたbytesを返すtest-only readerを提供する.

    Attributes:
        read_blob_ids (list[int]): read_bytesへ渡されたblob識別子.
        _content (bytes): read_bytesが常に返すstored bytes.
    """

    read_blob_ids: list[int]

    def __init__(self, content: bytes) -> None:
        """固定stored bytesを返すreaderを初期化する.

        Args:
            content (bytes): read_bytesが返すsynthetic blob content.
        """
        self._content: bytes = content
        self.read_blob_ids = []

    async def read_bytes(self, blob_id: int) -> bytes:
        """Blob IDを記録して固定stored bytesを返す.

        Args:
            blob_id (int): 読み込むblobの識別子.

        Returns:
            bytes: 初期化時に指定されたstored bytes.
        """
        self.read_blob_ids.append(blob_id)
        return self._content


class FailingBlobByteReader:
    """指定された例外を送出するtest-only readerを提供する.

    Attributes:
        _error (Exception): read_bytesで常に送出するbackend error.
    """

    def __init__(self, error: Exception) -> None:
        """送出するbackend errorでreaderを初期化する.

        Args:
            error (Exception): blob IDにかかわらず送出する例外.
        """
        self._error: Exception = error

    async def read_bytes(self, blob_id: int) -> bytes:
        """Blob IDにかかわらず指定されたbackend errorを送出する.

        Args:
            blob_id (int): production interfaceと互換に受け取るblob識別子.

        Raises:
            Exception: 初期化時に指定されたbackend error.
        """
        _ = blob_id
        raise self._error


async def test_blob_byte_reader_adapter_returns_reader_bytes() -> None:
    """adapterがreaderのbytesをそのまま返す境界契約を検証する.

    固定bytesを返すreaderでadapterを実行し,response bytesとreaderへ渡すblob IDが一致する
    ことを確認する.

    Returns:
        None: 返却bytesとreader呼び出し記録を検証して完了する.
    """
    reader = StaticBlobByteReader(b"ok")
    adapter = BlobByteReaderAdapter(reader)

    result = await adapter.read_bytes(42)

    assert result == b"ok"
    assert reader.read_blob_ids == [42]


async def test_blob_byte_reader_adapter_converts_configured_unavailable_error() -> None:
    """Configured unavailable errorがquery用errorへ変換される契約を検証する.

    非公開detailを含むbackend errorをconfigured typeとして与え,adapterがblob IDだけを公開する
    BlobBytesUnavailableErrorへ変換することを確認する.

    Returns:
        None: 変換後error,cause,公開文字列からのprivate detail除外を検証して完了する.
    """
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
    """既存のquery unavailable errorが同一instanceのまま伝播する契約を検証する.

    BlobBytesUnavailableErrorを送出するreaderでadapterを実行し,別errorへ再変換せず同一instanceを送出することを確認する.

    Returns:
        None: 送出されたerror instanceの同一性を検証して完了する.
    """
    unavailable_error = BlobBytesUnavailableError(blob_id=404)
    adapter = BlobByteReaderAdapter(FailingBlobByteReader(unavailable_error))

    with pytest.raises(BlobBytesUnavailableError) as exc_info:
        _ = await adapter.read_bytes(99)

    assert exc_info.value is unavailable_error


async def test_blob_byte_reader_adapter_preserves_unexpected_exceptions() -> None:
    """configuredされていないbackend errorがそのまま伝播する契約を検証する.

    RuntimeErrorを送出するreaderでadapterを実行し,unavailable errorへ変換せず同一instanceを
    送出することを確認する.

    Returns:
        None: 予期しないerror instanceの同一性を検証して完了する.
    """
    unexpected_error = RuntimeError("backend_detail=SYNTHETIC_PRIVATE_BLOB_LOCATION")
    adapter = BlobByteReaderAdapter(FailingBlobByteReader(unexpected_error))

    with pytest.raises(RuntimeError) as exc_info:
        _ = await adapter.read_bytes(123)

    assert exc_info.value is unexpected_error
