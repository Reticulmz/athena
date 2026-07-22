"""query serviceがblob bytesをbackend detailなしで読むboundaryを定義する."""

from __future__ import annotations

from typing import Protocol


class BlobBytesUnavailableError(FileNotFoundError):
    """query workflowでblob bytesを利用できないことを表す例外.

    Attributes:
        blob_id (int): query repositoryが返したblob ID.

    Notes:
        storage keyとfilesystem pathとbackend detailとraw bytesを保持しない. str()とrepr()に
        出る値はblob IDと固定文言だけである.
    """

    blob_id: int

    def __init__(self, blob_id: int) -> None:
        """利用不能なblobを識別するIDだけを保持して例外messageを初期化する.

        Args:
            blob_id (int): query repositoryが返したblob ID.
        """
        self.blob_id = blob_id
        super().__init__(f"blob bytes are unavailable: blob_id={blob_id}")


class BlobByteReader(Protocol):
    """query workflowへblob bytes readだけを公開するprotocolを定義する.

    Notes:
        実装はstorage keyとfilesystem pathとbackend detailをresponse側へ公開しない.
    """

    async def read_bytes(self, blob_id: int) -> bytes:
        """Blob IDに対応するbytesを読み込む.

        Args:
            blob_id (int): query repositoryが返したblob ID.

        Returns:
            bytes: blob IDに対応するraw bytes.

        Raises:
            BlobBytesUnavailableError: blob metadataまたはbackend contentが利用できない場合.

        Notes:
            storage backend keyとfilesystem pathとblob implementation detailは返さない.
        """
        ...


class BlobByteReaderAdapter:
    """既存readerをquery-layer BlobByteReaderとして包むadapterを定義する.

    Attributes:
        _reader (BlobByteReader): raw bytesを読む既存reader.
        _unavailable_exception_types (tuple[type[Exception], ...]): query-layer unavailable
            errorへ変換するexception type列.

    Notes:
        変換後errorはblob IDだけを保持してbackend detailを公開しない. 想定外exceptionは
        変換せずcallerへ伝播する.
    """

    def __init__(
        self,
        reader: BlobByteReader,
        *,
        unavailable_exception_types: tuple[type[Exception], ...] = (),
    ) -> None:
        """既存readerとunavailable errorへ変換するexception type列を保持する.

        Args:
            reader (BlobByteReader): read_bytes(blob_id)を持つread-only reader.
            unavailable_exception_types (tuple[type[Exception], ...]): BlobBytesUnavailableErrorへ
                変換するexception type列.
        """
        self._reader: BlobByteReader = reader
        self._unavailable_exception_types: tuple[type[Exception], ...] = (
            unavailable_exception_types
        )

    async def read_bytes(self, blob_id: int) -> bytes:
        """Blob IDからbytesを読み設定済みunavailable exceptionだけを変換する.

        Args:
            blob_id (int): query repositoryが返したblob ID.

        Returns:
            bytes: blob IDに対応するraw bytes.

        Raises:
            BlobBytesUnavailableError: readerがunavailable errorまたは設定済みexceptionを
                送出した場合.
            Exception: 設定済みunavailable exception以外を変換せず再送出した場合.

        Notes:
            causeの詳細は保持してもquery-layer errorのmessageには混ぜない.
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
