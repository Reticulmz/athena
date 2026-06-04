from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

import pytest

from osu_server.infrastructure.storage.errors import (
    BackendWriteError,
    BlobContentMissingError,
    BlobStorageConfigurationError,
)
from osu_server.infrastructure.storage.local import LocalBlobStorageBackend

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


def sha256_storage_key(content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    return f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"


def final_storage_path(root: Path, content: bytes) -> Path:
    digest = hashlib.sha256(content).hexdigest()
    return root / "sha256" / digest[:2] / digest[2:4] / digest


async def collect_chunks(chunks: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in chunks])


async def test_validate_configuration_creates_missing_writable_root(tmp_path: Path) -> None:
    root = tmp_path / "blob-root"
    backend = LocalBlobStorageBackend(root)

    await backend.validate_configuration()

    assert root.is_dir()
    staged = await backend.begin_write()
    await staged.write(b"writable")
    await staged.discard()


async def test_validate_configuration_rejects_file_root(tmp_path: Path) -> None:
    root = tmp_path / "not-a-directory"
    _ = root.write_text("not a directory", encoding="utf-8")
    backend = LocalBlobStorageBackend(root)

    with pytest.raises(BlobStorageConfigurationError):
        await backend.validate_configuration()


async def test_validate_configuration_rejects_uncreatable_final_storage_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_mkdir = type(tmp_path).mkdir
    blocked_final_directory = tmp_path / "sha256" / "00" / "00"

    def fail_final_storage_mkdir(
        self: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if self == blocked_final_directory:
            raise OSError("final storage directory cannot be created")
        original_mkdir(self, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(type(tmp_path), "mkdir", fail_final_storage_mkdir)
    backend = LocalBlobStorageBackend(tmp_path)

    with pytest.raises(BlobStorageConfigurationError):
        await backend.validate_configuration()


async def test_staged_content_becomes_readable_only_after_finalize(tmp_path: Path) -> None:
    backend = LocalBlobStorageBackend(tmp_path)
    await backend.validate_configuration()
    content = b"hello from multiple chunks"
    storage_key = sha256_storage_key(content)

    staged = await backend.begin_write()
    await staged.write(content[:6])
    await staged.write(content[6:])

    assert not await backend.exists(storage_key)
    with pytest.raises(BlobContentMissingError):
        _ = await backend.open_read(storage_key)

    await staged.finalize(storage_key)

    assert await backend.exists(storage_key)
    assert await collect_chunks(await backend.open_read(storage_key)) == content


async def test_open_read_streams_finalized_content_in_backend_chunks(
    tmp_path: Path,
) -> None:
    backend = LocalBlobStorageBackend(tmp_path, read_chunk_size=4)
    await backend.validate_configuration()
    content = b"chunked-final-content"
    storage_key = sha256_storage_key(content)

    staged = await backend.begin_write()
    await staged.write(content)
    await staged.finalize(storage_key)

    chunks = [chunk async for chunk in await backend.open_read(storage_key)]

    assert chunks == [b"chun", b"ked-", b"fina", b"l-co", b"nten", b"t"]


async def test_missing_valid_storage_key_is_unavailable_content(
    tmp_path: Path,
) -> None:
    backend = LocalBlobStorageBackend(tmp_path)
    await backend.validate_configuration()
    content = b"missing finalized content"
    storage_key = sha256_storage_key(content)

    assert not await backend.exists(storage_key)
    with pytest.raises(BlobContentMissingError) as exc_info:
        _ = await backend.open_read(storage_key)

    assert exc_info.value.storage_key == storage_key


async def test_user_filename_like_keys_are_missing_and_never_read_as_paths(
    tmp_path: Path,
) -> None:
    backend = LocalBlobStorageBackend(tmp_path)
    await backend.validate_configuration()
    filename_path = tmp_path / "avatar.png"
    _ = filename_path.write_bytes(b"user filename content")

    assert not await backend.exists("avatar.png")
    with pytest.raises(BlobContentMissingError) as exc_info:
        _ = await backend.open_read("avatar.png")

    assert exc_info.value.storage_key == "avatar.png"


async def test_path_traversal_like_keys_are_missing_and_never_read_outside_root(
    tmp_path: Path,
) -> None:
    backend = LocalBlobStorageBackend(tmp_path / "blob-root")
    await backend.validate_configuration()
    outside_path = tmp_path / "outside.bin"
    _ = outside_path.write_bytes(b"outside content")

    assert not await backend.exists("../outside.bin")
    with pytest.raises(BlobContentMissingError) as exc_info:
        _ = await backend.open_read("../outside.bin")

    assert exc_info.value.storage_key == "../outside.bin"


async def test_finalize_existing_key_is_idempotent_and_does_not_overwrite(
    tmp_path: Path,
) -> None:
    backend = LocalBlobStorageBackend(tmp_path)
    await backend.validate_configuration()
    content = b"original content"
    storage_key = sha256_storage_key(content)

    first_write = await backend.begin_write()
    await first_write.write(content)
    await first_write.finalize(storage_key)

    duplicate_write = await backend.begin_write()
    await duplicate_write.write(b"different staged content")
    await duplicate_write.finalize(storage_key)

    assert await collect_chunks(await backend.open_read(storage_key)) == content
    assert not any((tmp_path / ".tmp").iterdir())


async def test_finalize_rejects_existing_directory_at_final_path(
    tmp_path: Path,
) -> None:
    backend = LocalBlobStorageBackend(tmp_path)
    await backend.validate_configuration()
    content = b"directory at final path"
    storage_key = sha256_storage_key(content)
    final_path = final_storage_path(tmp_path, content)
    final_path.mkdir(parents=True)

    staged = await backend.begin_write()
    await staged.write(content)

    with pytest.raises(BackendWriteError):
        await staged.finalize(storage_key)

    assert final_path.is_dir()
    assert not await backend.exists(storage_key)
    with pytest.raises(BlobContentMissingError):
        _ = await backend.open_read(storage_key)
    assert not any((tmp_path / ".tmp").iterdir())


async def test_finalize_rejects_existing_symlink_at_final_path(
    tmp_path: Path,
) -> None:
    backend = LocalBlobStorageBackend(tmp_path)
    await backend.validate_configuration()
    content = b"symlink at final path"
    storage_key = sha256_storage_key(content)
    final_path = final_storage_path(tmp_path, content)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    symlink_target = tmp_path / "not-finalized-content"
    _ = symlink_target.write_bytes(b"not the staged blob")
    final_path.symlink_to(symlink_target)

    staged = await backend.begin_write()
    await staged.write(content)

    with pytest.raises(BackendWriteError):
        await staged.finalize(storage_key)

    assert final_path.is_symlink()
    assert not await backend.exists(storage_key)
    with pytest.raises(BlobContentMissingError):
        _ = await backend.open_read(storage_key)
    assert not any((tmp_path / ".tmp").iterdir())


async def test_finalize_rejects_file_exists_race_with_non_file_final_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = LocalBlobStorageBackend(tmp_path)
    await backend.validate_configuration()
    content = b"file exists race"
    storage_key = sha256_storage_key(content)
    final_path = final_storage_path(tmp_path, content)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    def create_directory_then_raise(src: object, dst: object) -> None:
        _ = src
        if dst != final_path:
            raise AssertionError("unexpected final path")
        final_path.mkdir()
        raise FileExistsError("final path race")

    monkeypatch.setattr(os, "link", create_directory_then_raise)
    staged = await backend.begin_write()
    await staged.write(content)

    with pytest.raises(BackendWriteError):
        await staged.finalize(storage_key)

    assert final_path.is_dir()
    assert not await backend.exists(storage_key)
    with pytest.raises(BlobContentMissingError):
        _ = await backend.open_read(storage_key)
    assert not any((tmp_path / ".tmp").iterdir())


async def test_failed_staging_write_leaves_no_final_blob_exposed(tmp_path: Path) -> None:
    backend = LocalBlobStorageBackend(tmp_path)
    await backend.validate_configuration()
    content = b"staging write should fail"
    storage_key = sha256_storage_key(content)
    staged = await backend.begin_write()
    tmp_staging_root = tmp_path / ".tmp"

    for staged_path in tmp_staging_root.iterdir():
        staged_path.unlink()
    tmp_staging_root.rmdir()

    with pytest.raises(BackendWriteError):
        await staged.write(content)

    assert not await backend.exists(storage_key)
    with pytest.raises(BlobContentMissingError):
        _ = await backend.open_read(storage_key)


async def test_finalize_rejects_non_sha256_storage_key_without_exposing_blob(
    tmp_path: Path,
) -> None:
    backend = LocalBlobStorageBackend(tmp_path)
    await backend.validate_configuration()
    content = b"staged but invalid final key"
    digest = hashlib.sha256(content).hexdigest()
    valid_storage_key = sha256_storage_key(content)
    invalid_storage_keys = (
        "../sha256/aa/bb/not-a-digest",
        f"sha256/{digest[:2]}/{digest[2:4]}/{digest.upper()}",
        f"sha256/00/00/{digest}",
    )

    for invalid_storage_key in invalid_storage_keys:
        staged = await backend.begin_write()
        await staged.write(content)

        with pytest.raises(BackendWriteError):
            await staged.finalize(invalid_storage_key)

        assert not any((tmp_path / ".tmp").iterdir())

    assert not await backend.exists(valid_storage_key)
    with pytest.raises(BlobContentMissingError):
        _ = await backend.open_read(valid_storage_key)


async def test_discarded_staging_never_exposes_final_blob(tmp_path: Path) -> None:
    backend = LocalBlobStorageBackend(tmp_path)
    await backend.validate_configuration()
    content = b"discard me"
    storage_key = sha256_storage_key(content)

    staged = await backend.begin_write()
    await staged.write(content)
    await staged.discard()

    assert not await backend.exists(storage_key)
    with pytest.raises(BlobContentMissingError):
        _ = await backend.open_read(storage_key)
