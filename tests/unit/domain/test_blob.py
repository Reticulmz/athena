from datetime import UTC, datetime

import pytest

from osu_server.domain.storage.blobs import Blob, BlobStorageBackendKind, InvalidBlobError
from tests.support.runtime_assertions import assert_rejects_setattr

VALID_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
VALID_STORAGE_KEY = f"e3/b0/{VALID_SHA256}"
UPPERCASE_SHA256 = "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855"
NON_HEX_SHA256 = "g3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_blob_creation_valid() -> None:
    now = datetime.now(UTC)
    blob = Blob(
        id=1,
        sha256=VALID_SHA256,
        byte_size=0,
        content_type="application/octet-stream",
        storage_backend="local",
        storage_key=VALID_STORAGE_KEY,
        created_at=now,
    )

    assert blob.id == 1
    assert blob.sha256 == VALID_SHA256
    assert blob.byte_size == 0
    assert blob.content_type == "application/octet-stream"
    assert blob.storage_backend == "local"
    assert blob.storage_key == VALID_STORAGE_KEY
    assert blob.created_at == now


def test_blob_rejects_empty_content_type() -> None:
    with pytest.raises(InvalidBlobError, match="content_type must not be empty"):
        _ = Blob(
            id=1,
            sha256=VALID_SHA256,
            byte_size=0,
            content_type="",
            storage_backend="local",
            storage_key="key",
            created_at=datetime.now(UTC),
        )


def test_blob_rejects_negative_byte_size() -> None:
    with pytest.raises(InvalidBlobError, match="byte_size must be non-negative"):
        _ = Blob(
            id=1,
            sha256=VALID_SHA256,
            byte_size=-1,
            content_type="text/plain",
            storage_backend="local",
            storage_key="key",
            created_at=datetime.now(UTC),
        )


def test_blob_rejects_invalid_sha256() -> None:
    # Not 64 characters
    with pytest.raises(
        InvalidBlobError, match="sha256 must be a 64-character lowercase hexadecimal string"
    ):
        _ = Blob(
            id=1,
            sha256="short",
            byte_size=10,
            content_type="text/plain",
            storage_backend="local",
            storage_key="key",
            created_at=datetime.now(UTC),
        )

    # Uppercase
    with pytest.raises(
        InvalidBlobError, match="sha256 must be a 64-character lowercase hexadecimal string"
    ):
        _ = Blob(
            id=1,
            sha256=UPPERCASE_SHA256,
            byte_size=10,
            content_type="text/plain",
            storage_backend="local",
            storage_key="key",
            created_at=datetime.now(UTC),
        )

    # Non-hex characters
    with pytest.raises(
        InvalidBlobError, match="sha256 must be a 64-character lowercase hexadecimal string"
    ):
        _ = Blob(
            id=1,
            sha256=NON_HEX_SHA256,
            byte_size=10,
            content_type="text/plain",
            storage_backend="local",
            storage_key="key",
            created_at=datetime.now(UTC),
        )


def test_blob_rejects_missing_storage_backend() -> None:
    with pytest.raises(InvalidBlobError, match="storage_backend must not be empty"):
        _ = Blob(
            id=1,
            sha256=VALID_SHA256,
            byte_size=10,
            content_type="text/plain",
            storage_backend="",
            storage_key="key",
            created_at=datetime.now(UTC),
        )


def test_blob_rejects_unknown_storage_backend() -> None:
    with pytest.raises(InvalidBlobError, match="unknown storage_backend: memory"):
        _ = Blob(
            id=1,
            sha256=VALID_SHA256,
            byte_size=10,
            content_type="text/plain",
            storage_backend="memory",
            storage_key="key",
            created_at=datetime.now(UTC),
        )


def test_blob_storage_backend_kind_is_closed_value_set() -> None:
    assert {backend.value for backend in BlobStorageBackendKind} == {"local", "s3"}


def test_blob_rejects_missing_storage_key() -> None:
    with pytest.raises(InvalidBlobError, match="storage_key must not be empty"):
        _ = Blob(
            id=1,
            sha256=VALID_SHA256,
            byte_size=10,
            content_type="text/plain",
            storage_backend="local",
            storage_key="",
            created_at=datetime.now(UTC),
        )


def test_blob_has_no_attachment_fields() -> None:
    # Ensure domain fields like original_filename are NOT part of the Blob entity
    # as per 1.3, 9.4
    now = datetime.now(UTC)

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        _ = Blob(
            id=1,
            sha256=VALID_SHA256,
            byte_size=0,
            content_type="application/octet-stream",
            storage_backend="local",
            storage_key="key",
            created_at=now,
            original_filename="test.osu",  # pyright: ignore[reportCallIssue]
        )

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        _ = Blob(
            id=1,
            sha256=VALID_SHA256,
            byte_size=0,
            content_type="application/octet-stream",
            storage_backend="local",
            storage_key="key",
            created_at=now,
            uploaded_by_user_id=123,  # pyright: ignore[reportCallIssue]
        )


def test_blob_is_immutable() -> None:
    now = datetime.now(UTC)
    blob = Blob(
        id=1,
        sha256=VALID_SHA256,
        byte_size=0,
        content_type="application/octet-stream",
        storage_backend="local",
        storage_key="key",
        created_at=now,
    )

    assert_rejects_setattr(blob, "byte_size", 1)
