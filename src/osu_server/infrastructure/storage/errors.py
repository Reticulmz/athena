"""Typed errors for blob storage backends."""

from __future__ import annotations


class BlobStorageConfigurationError(RuntimeError):
    """Raised when blob storage backend configuration is invalid."""


class UnsupportedBlobStorageBackendError(BlobStorageConfigurationError):
    """Raised when a configured backend is recognized but unavailable."""

    backend: str

    def __init__(self, backend: str) -> None:
        self.backend = backend
        super().__init__(f"unsupported blob storage backend: {backend}")


class BlobContentMissingError(FileNotFoundError):
    """Raised when backend content is missing for an existing storage key."""

    storage_key: str

    def __init__(self, storage_key: str) -> None:
        self.storage_key = storage_key
        super().__init__(f"blob content is missing for storage key: {storage_key}")


class BackendReadError(OSError):
    """Raised when a backend cannot read blob content."""

    storage_key: str

    def __init__(self, storage_key: str, message: str | None = None) -> None:
        self.storage_key = storage_key
        super().__init__(message or f"failed to read blob content: {storage_key}")


class BackendWriteError(OSError):
    """Raised when a backend cannot write or finalize blob content."""
