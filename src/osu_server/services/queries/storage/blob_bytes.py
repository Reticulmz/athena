"""Blob byte read boundary for query services."""

from __future__ import annotations

from typing import Protocol


class BlobBytesUnavailableError(FileNotFoundError):
    """Blob bytes が query workflow で利用できないことを表す例外です。

    Args:
        blob_id: query repository が返した blob id。

    Returns:
        なし。

    Raises:
        なし。

    Constraints:
        storage key、filesystem path、backend detail、raw bytes は保持しません。
        `str()` と `repr()` に出る値は blob id と固定文言だけです。
    """

    blob_id: int

    def __init__(self, blob_id: int) -> None:
        self.blob_id = blob_id
        super().__init__(f"blob bytes are unavailable: blob_id={blob_id}")


class BlobByteReader(Protocol):
    """Query workflow に blob bytes read だけを公開する protocol です。

    Args:
        なし。

    Returns:
        なし。

    Raises:
        なし。

    Constraints:
        実装は storage key、filesystem path、backend detail を response 側へ公開しません。
    """

    async def read_bytes(self, blob_id: int) -> bytes:
        """blob id に対応する bytes を読み込みます。

        Args:
            blob_id: query repository が返した blob id。

        Returns:
            blob id に対応する blob bytes。

        Raises:
            BlobBytesUnavailableError: blob metadata または backend content が利用できない場合。

        Constraints:
            storage backend key、filesystem path、blob implementation detail は返しません。
        """
        ...


class BlobByteReaderAdapter:
    """既存 reader を query-layer `BlobByteReader` として包む adapter です。

    Args:
        reader: `read_bytes(blob_id)` を持つ read-only reader。
        unavailable_exception_types: query-layer unavailable error に変換する例外型。

    Returns:
        なし。

    Raises:
        なし。

    Constraints:
        変換後の error は blob id だけを保持し、backend detail を公開しません。
        想定外の例外は変換せず、そのまま呼び出し元へ伝播します。
    """

    def __init__(
        self,
        reader: BlobByteReader,
        *,
        unavailable_exception_types: tuple[type[Exception], ...] = (),
    ) -> None:
        self._reader: BlobByteReader = reader
        self._unavailable_exception_types: tuple[type[Exception], ...] = (
            unavailable_exception_types
        )

    async def read_bytes(self, blob_id: int) -> bytes:
        """blob id から bytes を読み、設定済み unavailable 例外だけを変換します。

        Args:
            blob_id: query repository が返した blob id。

        Returns:
            blob id に対応する blob bytes。

        Raises:
            BlobBytesUnavailableError: reader が query-layer unavailable error を投げた場合、
                または設定済み unavailable 例外型を投げた場合。
            Exception: 設定済み unavailable 例外以外は変換せず再送出します。

        Constraints:
            cause の詳細は保持しても、query-layer error の message には混ぜません。
        """
        try:
            return await self._reader.read_bytes(blob_id)
        except BlobBytesUnavailableError:
            raise
        except Exception as exc:
            if isinstance(exc, self._unavailable_exception_types):
                raise BlobBytesUnavailableError(blob_id) from exc
            raise


__all__ = [
    "BlobByteReader",
    "BlobByteReaderAdapter",
    "BlobBytesUnavailableError",
]
