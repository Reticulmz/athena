import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class InvalidBlobError(ValueError):
    """Raised when blob metadata violates domain invariants."""


class BlobStorageBackendKind(StrEnum):
    """Blob metadataへ記録するstorage backend kindの閉集合.

    Attributes:
        LOCAL (str): Local filesystem backendの永続化値.
        S3 (str): S3互換object storage backendの永続化値.

    Notes:
        Domain内ではEnum memberを使い、設定/DB境界だけで文字列値へ変換する.
    """

    LOCAL = "local"
    S3 = "s3"


@dataclass(frozen=True, slots=True)
class Blob:
    """永続化済み blob metadata.

    Attributes:
        id (int): repositoryが割り当てたBlob ID.
        sha256 (str): content-addressingに使用するSHA-256 digest.
        byte_size (int): blob本体のbyte数.
        content_type (str): blob本体のmedia type.
        storage_backend (BlobStorageBackendKind): 本体を保持するbackend kind.
        storage_key (str): backend内でblob本体を識別するkey.
        created_at (datetime): metadataを永続化した日時.

    Notes:
        sha256は64文字の小文字16進数、byte_sizeは0以上、文字列値は空を許可しない.
    """

    id: int
    sha256: str
    byte_size: int
    content_type: str
    storage_backend: BlobStorageBackendKind
    storage_key: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.content_type:
            raise InvalidBlobError("content_type must not be empty")

        if self.byte_size < 0:
            raise InvalidBlobError("byte_size must be non-negative")

        if not SHA256_PATTERN.match(self.sha256):
            raise InvalidBlobError("sha256 must be a 64-character lowercase hexadecimal string")

        _validate_storage_backend(self.storage_backend)

        if not self.storage_key:
            raise InvalidBlobError("storage_key must not be empty")


@dataclass(frozen=True, slots=True)
class NewBlob:
    """repositoryがIDと作成日時を割り当てる前のBlob metadataを表す.

    Attributes:
        sha256 (str): content-addressingに使用するSHA-256 digest.
        byte_size (int): blob本体のbyte数.
        content_type (str): blob本体のmedia type.
        storage_backend (BlobStorageBackendKind): 本体を保持するbackend kind.
        storage_key (str): backend内でblob本体を識別するkey.

    Notes:
        sha256は64文字の小文字16進数、byte_sizeは0以上、文字列値は空を許可しない.
    """

    sha256: str
    byte_size: int
    content_type: str
    storage_backend: BlobStorageBackendKind
    storage_key: str

    def __post_init__(self) -> None:
        if not self.content_type:
            raise InvalidBlobError("content_type must not be empty")

        if self.byte_size < 0:
            raise InvalidBlobError("byte_size must be non-negative")

        if not SHA256_PATTERN.match(self.sha256):
            raise InvalidBlobError("sha256 must be a 64-character lowercase hexadecimal string")

        _validate_storage_backend(self.storage_backend)

        if not self.storage_key:
            raise InvalidBlobError("storage_key must not be empty")


@dataclass(frozen=True, slots=True)
class BlobStored:
    """Result for newly persisted blob content."""

    blob: Blob


@dataclass(frozen=True, slots=True)
class BlobDeduplicated:
    """Result for content that matched an existing blob."""

    blob: Blob


type BlobStoreResult = BlobStored | BlobDeduplicated


def _validate_storage_backend(value: object) -> None:
    if value == "":
        raise InvalidBlobError("storage_backend must not be empty")
    if not isinstance(value, BlobStorageBackendKind):
        raise InvalidBlobError(f"unknown storage_backend: {value}")
