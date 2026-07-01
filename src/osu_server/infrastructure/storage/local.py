"""Local filesystem blob storage backend."""

from __future__ import annotations

import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Final

from osu_server.infrastructure.storage.errors import (
    BackendReadError,
    BackendWriteError,
    BlobContentMissingError,
    BlobStorageConfigurationError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from osu_server.infrastructure.storage.interfaces import ByteChunks, StagedBlobWrite

_READ_CHUNK_SIZE: Final = 1024 * 1024
_SHA256_STORAGE_KEY_PATTERN: Final = re.compile(
    r"\Asha256/([0-9a-f]{2})/([0-9a-f]{2})/([0-9a-f]{64})\Z",
)


class LocalBlobStorageBackend:
    """Content-addressed blob backend rooted in a local directory."""

    _root: Path
    _tmp_root: Path
    _read_chunk_size: int

    def __init__(
        self,
        root: str | Path,
        *,
        read_chunk_size: int = _READ_CHUNK_SIZE,
    ) -> None:
        self._root = Path(root)
        self._tmp_root = self._root / ".tmp"
        self._read_chunk_size = read_chunk_size

    async def validate_configuration(self) -> None:
        """Create and validate the root and staging directory."""
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BlobStorageConfigurationError(
                f"local blob storage root cannot be created: {self._root}",
            ) from exc

        if not self._root.is_dir():
            raise BlobStorageConfigurationError(
                f"local blob storage root is not a directory: {self._root}",
            )

        try:
            self._tmp_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BlobStorageConfigurationError(
                f"local blob storage temporary path cannot be created: {self._tmp_root}",
            ) from exc

        if not self._tmp_root.is_dir():
            raise BlobStorageConfigurationError(
                f"local blob storage temporary path is not a directory: {self._tmp_root}",
            )

        try:
            probe_path = self._create_stage_path()
            _ = probe_path.write_bytes(b"")
            probe_path.unlink()
        except OSError as exc:
            raise BlobStorageConfigurationError(
                f"local blob storage root is not writable: {self._root}",
            ) from exc

        self._validate_final_storage_directory()

    async def begin_write(self) -> StagedBlobWrite:
        """Start a staged write under the backend temporary directory."""
        await self.validate_configuration()
        try:
            return _LocalStagedBlobWrite(
                root=self._root,
                stage_path=self._create_stage_path(),
            )
        except OSError as exc:
            raise BackendWriteError("failed to create local blob staging file") from exc

    async def open_read(self, storage_key: str) -> ByteChunks:
        """Open a chunk stream for an existing finalized blob."""
        path = _final_path_for_read(self._root, storage_key)
        if path is None or not _is_finalized_file(path):
            raise BlobContentMissingError(storage_key)

        async def chunks() -> AsyncIterator[bytes]:
            try:
                with path.open("rb") as blob_file:
                    while chunk := blob_file.read(self._read_chunk_size):
                        yield chunk
            except FileNotFoundError as exc:
                raise BlobContentMissingError(storage_key) from exc
            except OSError as exc:
                raise BackendReadError(storage_key) from exc

        return chunks()

    async def exists(self, storage_key: str) -> bool:
        """Return whether a finalized blob exists for the storage key."""
        path = _final_path_for_read(self._root, storage_key)
        return path is not None and _is_finalized_file(path)

    def _create_stage_path(self) -> Path:
        file_descriptor, path = tempfile.mkstemp(
            prefix="blob-",
            suffix=".part",
            dir=self._tmp_root,
        )
        os.close(file_descriptor)
        return Path(path)

    def _validate_final_storage_directory(self) -> None:
        probe_directory = self._root / "sha256" / "00" / "00"
        probe_path: Path | None = None

        try:
            probe_directory.mkdir(parents=True, exist_ok=True)
            _ensure_probe_directory(probe_directory)
            file_descriptor, path = tempfile.mkstemp(
                prefix=".probe-",
                dir=probe_directory,
            )
            os.close(file_descriptor)
            probe_path = Path(path)
        except BlobStorageConfigurationError:
            raise
        except OSError as exc:
            raise BlobStorageConfigurationError(
                f"local blob storage final path is not writable: {probe_directory}",
            ) from exc
        finally:
            if probe_path is not None:
                with suppress(OSError):
                    probe_path.unlink(missing_ok=True)


class _LocalStagedBlobWrite:
    _root: Path
    _stage_path: Path
    _closed: bool

    def __init__(self, *, root: Path, stage_path: Path) -> None:
        self._root = root
        self._stage_path = stage_path
        self._closed = False

    async def write(self, chunk: bytes) -> None:
        """Append bytes to the staged file."""
        self._ensure_open()
        try:
            with self._stage_path.open("ab") as staged_file:
                _ = staged_file.write(chunk)
        except OSError as exc:
            self._discard_without_error()
            self._closed = True
            raise BackendWriteError("failed to write local blob staging content") from exc

    async def finalize(self, storage_key: str) -> None:
        """Atomically publish staged bytes to a SHA-256-derived final key."""
        self._ensure_open()
        final_path: Path | None = None

        try:
            final_path = _final_path_for_write(self._root, storage_key)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            _ensure_under_root(self._root, final_path)
            if final_path.exists():
                _ensure_existing_finalized_file(final_path, storage_key)
                self._discard_without_error()
                self._closed = True
                return

            os.link(self._stage_path, final_path)
        except FileExistsError:
            if final_path is None:
                self._discard_without_error()
                self._closed = True
                raise BackendWriteError(f"failed to finalize local blob: {storage_key}") from None
            try:
                _ensure_existing_finalized_file(final_path, storage_key)
            except BackendWriteError:
                self._discard_without_error()
                self._closed = True
                raise
            self._discard_without_error()
            self._closed = True
            return
        except BackendWriteError:
            self._discard_without_error()
            self._closed = True
            raise
        except OSError as exc:
            self._discard_without_error()
            self._closed = True
            raise BackendWriteError(f"failed to finalize local blob: {storage_key}") from exc

        self._discard_without_error()
        self._closed = True

    async def discard(self) -> None:
        """Discard the staged file without exposing final content."""
        if self._closed:
            return
        try:
            self._stage_path.unlink(missing_ok=True)
        except OSError as exc:
            raise BackendWriteError("failed to discard local blob staging content") from exc
        finally:
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise BackendWriteError("local blob staging write is already closed")

    def _discard_without_error(self) -> None:
        with suppress(OSError):
            self._stage_path.unlink(missing_ok=True)


def _final_path_for_read(root: Path, storage_key: str) -> Path | None:
    digest = _storage_key_digest(storage_key)
    if digest is None:
        return None

    final_path = root / "sha256" / digest[:2] / digest[2:4] / digest
    if not _is_under_root(root, final_path):
        return None
    return final_path


def _final_path_for_write(root: Path, storage_key: str) -> Path:
    digest = _storage_key_digest(storage_key)
    if digest is None:
        raise BackendWriteError(f"invalid SHA-256 storage key: {storage_key}")

    final_path = root / "sha256" / digest[:2] / digest[2:4] / digest
    _ensure_under_root(root, final_path)
    return final_path


def _storage_key_digest(storage_key: str) -> str | None:
    match = _SHA256_STORAGE_KEY_PATTERN.fullmatch(storage_key)
    if match is None:
        return None

    first_prefix, second_prefix, digest = match.groups()
    if first_prefix != digest[:2] or second_prefix != digest[2:4]:
        return None
    return digest


def _ensure_under_root(root: Path, path: Path) -> None:
    if not _is_under_root(root, path):
        raise BackendWriteError(f"local blob path escapes storage root: {path}")


def _ensure_existing_finalized_file(path: Path, storage_key: str) -> None:
    if not _is_finalized_file(path):
        raise BackendWriteError(f"local blob final path is not a file: {storage_key}")


def _is_finalized_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _ensure_probe_directory(path: Path) -> None:
    if not path.is_dir():
        raise BlobStorageConfigurationError(
            f"local blob storage final path is not a directory: {path}",
        )


def _is_under_root(root: Path, path: Path) -> bool:
    try:
        _ = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True
