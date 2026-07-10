import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class InvalidBlobError(ValueError):
    """Raised when blob metadata violates domain invariants."""


class BlobStorageBackendKind(StrEnum):
    """blob metadata に記録する storage backend kind"""

    LOCAL = "local"
    S3 = "s3"


@dataclass(frozen=True, slots=True)
class Blob:
    id: int
    sha256: str
    byte_size: int
    content_type: str
    storage_backend: str
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
    """Blob metadata before repository-assigned identity and creation time exist."""

    sha256: str
    byte_size: int
    content_type: str
    storage_backend: str
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


def _validate_storage_backend(value: str) -> None:
    if not value:
        raise InvalidBlobError("storage_backend must not be empty")
    try:
        _ = BlobStorageBackendKind(value)
    except ValueError as exc:
        raise InvalidBlobError(f"unknown storage_backend: {value}") from exc
