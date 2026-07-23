"""Content-addressed Blob metadataの不変条件を検証するmodule.

Storage backendとSHA-256 validationおよびattachment責務との境界を対象にする.
"""

from datetime import UTC, datetime
from typing import cast

import pytest

from osu_server.domain.storage.blobs import (
    Blob,
    BlobStorageBackendKind,
    InvalidBlobError,
    NewBlob,
)
from tests.support.runtime_assertions import assert_rejects_setattr

VALID_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
VALID_STORAGE_KEY = f"e3/b0/{VALID_SHA256}"
UPPERCASE_SHA256 = "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855"
NON_HEX_SHA256 = "g3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_blob_creation_valid() -> None:
    """有効なBlob metadataが全fieldを保持することを検証する.

    正しいSHA-256とstorage backendでBlobを生成し永続identityとcontent metadataを確認する.

    Returns:
        None: 有効Blob生成の検証を完了する.
    """
    now = datetime.now(UTC)
    blob = Blob(
        id=1,
        sha256=VALID_SHA256,
        byte_size=0,
        content_type="application/octet-stream",
        storage_backend=BlobStorageBackendKind.LOCAL,
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
    """Blobが空のcontent_typeを拒否することを検証する.

    content_typeだけを空文字列にして生成しmedia type不変条件がInvalidBlobErrorになることを確認する.

    Returns:
        None: 空content type拒否の検証を完了する.
    """
    with pytest.raises(InvalidBlobError, match="content_type must not be empty"):
        _ = Blob(
            id=1,
            sha256=VALID_SHA256,
            byte_size=0,
            content_type="",
            storage_backend=BlobStorageBackendKind.LOCAL,
            storage_key="key",
            created_at=datetime.now(UTC),
        )


def test_blob_rejects_negative_byte_size() -> None:
    """Blobが負のbyte_sizeを拒否することを検証する.

    負数sizeで生成しcontent長が0以上というdomain不変条件がInvalidBlobErrorになることを確認する.

    Returns:
        None: 負のbyte size拒否の検証を完了する.
    """
    with pytest.raises(InvalidBlobError, match="byte_size must be non-negative"):
        _ = Blob(
            id=1,
            sha256=VALID_SHA256,
            byte_size=-1,
            content_type="text/plain",
            storage_backend=BlobStorageBackendKind.LOCAL,
            storage_key="key",
            created_at=datetime.now(UTC),
        )


def test_blob_rejects_invalid_sha256() -> None:
    """Blobが形式外のSHA-256 digestを拒否することを検証する.

    短い値と大文字値および16進数外の値を渡し固定長小文字digestの制約がInvalidBlobErrorになることを確認する.

    Returns:
        None: 無効SHA-256拒否の検証を完了する.
    """
    # Not 64 characters
    with pytest.raises(
        InvalidBlobError, match="sha256 must be a 64-character lowercase hexadecimal string"
    ):
        _ = Blob(
            id=1,
            sha256="short",
            byte_size=10,
            content_type="text/plain",
            storage_backend=BlobStorageBackendKind.LOCAL,
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
            storage_backend=BlobStorageBackendKind.LOCAL,
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
            storage_backend=BlobStorageBackendKind.LOCAL,
            storage_key="key",
            created_at=datetime.now(UTC),
        )


def test_blob_rejects_sha256_with_trailing_newline() -> None:
    """Blobが末尾改行を含むSHA-256 digestを拒否することを検証する.

    64文字のdigestへ改行を追加して生成し正確な固定長がInvalidBlobErrorで保護されることを確認する.

    Returns:
        None: 末尾改行を持つdigest拒否の検証を完了する.
    """
    with pytest.raises(
        InvalidBlobError, match="sha256 must be a 64-character lowercase hexadecimal string"
    ):
        _ = Blob(
            id=1,
            sha256="a" * 64 + "\n",
            byte_size=10,
            content_type="text/plain",
            storage_backend=BlobStorageBackendKind.LOCAL,
            storage_key="key",
            created_at=datetime.now(UTC),
        )


def test_new_blob_rejects_sha256_with_trailing_newline() -> None:
    """NewBlobが末尾改行を含むSHA-256 digestを拒否することを検証する.

    永続化前metadataへ改行付きdigestを渡しBlobと同じfixed-length validationが働くことを確認する.

    Returns:
        None: 新規Blobの末尾改行拒否の検証を完了する.
    """
    with pytest.raises(
        InvalidBlobError, match="sha256 must be a 64-character lowercase hexadecimal string"
    ):
        _ = NewBlob(
            sha256="a" * 64 + "\n",
            byte_size=10,
            content_type="text/plain",
            storage_backend=BlobStorageBackendKind.LOCAL,
            storage_key="key",
        )


def test_blob_rejects_missing_storage_backend() -> None:
    """Blobが空のstorage_backendを拒否することを検証する.

    backend値だけを空文字列として生成し保存先が必須である制約がInvalidBlobErrorになることを確認する.

    Returns:
        None: 空storage backend拒否の検証を完了する.
    """
    with pytest.raises(InvalidBlobError, match="storage_backend must not be empty"):
        _ = Blob(
            id=1,
            sha256=VALID_SHA256,
            byte_size=10,
            content_type="text/plain",
            storage_backend=cast("BlobStorageBackendKind", cast("object", "")),
            storage_key="key",
            created_at=datetime.now(UTC),
        )


def test_blob_rejects_unknown_storage_backend() -> None:
    """Blobが閉集合外のstorage_backendを拒否することを検証する.

    memoryという未定義backendを渡しLOCALまたはS3だけを受け入れる制約を確認する.

    Returns:
        None: 未知storage backend拒否の検証を完了する.
    """
    with pytest.raises(InvalidBlobError, match="unknown storage_backend: memory"):
        _ = Blob(
            id=1,
            sha256=VALID_SHA256,
            byte_size=10,
            content_type="text/plain",
            storage_backend=cast("BlobStorageBackendKind", cast("object", "memory")),
            storage_key="key",
            created_at=datetime.now(UTC),
        )


def test_blob_storage_backend_kind_is_closed_value_set() -> None:
    """BlobStorageBackendKindがLOCALとS3だけを持つことを検証する.

    enum memberの値集合を比較しbackend表現がLOCALとS3から増えていないことを確認する.

    Returns:
        None: storage backend閉集合の検証を完了する.
    """
    assert {backend.value for backend in BlobStorageBackendKind} == {"local", "s3"}


def test_blob_rejects_missing_storage_key() -> None:
    """Blobが空のstorage_keyを拒否することを検証する.

    storage keyを空文字列として生成しbackend内のcontent位置が必須である制約を確認する.

    Returns:
        None: 空storage key拒否の検証を完了する.
    """
    with pytest.raises(InvalidBlobError, match="storage_key must not be empty"):
        _ = Blob(
            id=1,
            sha256=VALID_SHA256,
            byte_size=10,
            content_type="text/plain",
            storage_backend=BlobStorageBackendKind.LOCAL,
            storage_key="",
            created_at=datetime.now(UTC),
        )


def test_blob_has_no_attachment_fields() -> None:
    """Blobがattachment固有fieldを持たないdomain境界を検証する.

    filenameとuploader IDをconstructorへ渡しBlob metadataに混在できずTypeErrorになることを確認する.

    Returns:
        None: Blobとattachment責務分離の検証を完了する.
    """
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
    """Blobが永続metadataとして生成後に変更できないことを検証する.

    有効なBlobのbyte_sizeへ代入を試みてvalue objectが変更を拒否することを確認する.

    Returns:
        None: Blob不変性の検証を完了する.
    """
    now = datetime.now(UTC)
    blob = Blob(
        id=1,
        sha256=VALID_SHA256,
        byte_size=0,
        content_type="application/octet-stream",
        storage_backend=BlobStorageBackendKind.LOCAL,
        storage_key="key",
        created_at=now,
    )

    assert_rejects_setattr(blob, "byte_size", 1)
