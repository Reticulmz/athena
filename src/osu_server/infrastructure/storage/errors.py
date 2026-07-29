"""blob storage backendが呼出側へ伝える型付きerrorを定義する."""

from __future__ import annotations


class BlobStorageConfigurationError(RuntimeError):
    """blob storage backendを使用可能にするconfigurationが不正な場合に送出する."""


class UnsupportedBlobStorageBackendError(BlobStorageConfigurationError):
    """指定されたblob storage backendを利用できない場合に送出する.

    Attributes:
        backend (str): 利用できなかったconfiguration上のbackend名.
    """

    backend: str

    def __init__(self, backend: str) -> None:
        """利用できないbackend名をerrorとattributeへ設定する.

        Args:
            backend (str): configurationで指定された未対応backend名.
        """
        self.backend = backend
        super().__init__(f"unsupported blob storage backend: {backend}")


class BlobContentMissingError(FileNotFoundError):
    """storage keyに対応するbackend contentが存在しない場合に送出する.

    Attributes:
        storage_key (str): contentが見つからなかった保存key.
    """

    storage_key: str

    def __init__(self, storage_key: str) -> None:
        """欠損したstorage keyをerrorとattributeへ設定する.

        Args:
            storage_key (str): contentが見つからなかった保存key.
        """
        self.storage_key = storage_key
        super().__init__(f"blob content is missing for storage key: {storage_key}")


class BackendReadError(OSError):
    """backendがblob contentを読み出せない場合に送出する.

    Attributes:
        storage_key (str): 読み出しに失敗した保存key.
    """

    storage_key: str

    def __init__(self, storage_key: str, message: str | None = None) -> None:
        """読み出し失敗のstorage keyと任意messageをerrorへ設定する.

        Args:
            storage_key (str): 読み出しに失敗した保存key.
            message (str | None): default messageを置き換える任意のerror message. ``None`` なら
                defaultを使う.
        """
        self.storage_key = storage_key
        super().__init__(message or f"failed to read blob content: {storage_key}")


class BackendWriteError(OSError):
    """backendがblob contentの書き込み,公開,または破棄に失敗した場合に送出する."""
