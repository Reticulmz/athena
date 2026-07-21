"""ローカルfilesystem上でcontent-addressed blobを安全に保存するbackendを実装する."""

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
    """ローカルdirectoryをrootにするcontent-addressed blob backendを提供する.

    Attributes:
        _root (Path): finalized blobを保存するroot directory.
        _tmp_root (Path): staged write fileを保存する ``.tmp`` directory.
        _read_chunk_size (int): 読み出しiteratorが ``read()`` へ渡すchunk size.
    """

    _root: Path
    _tmp_root: Path
    _read_chunk_size: int

    def __init__(
        self,
        root: str | Path,
        *,
        read_chunk_size: int = _READ_CHUNK_SIZE,
    ) -> None:
        """保存rootと読み出しchunk sizeを保持する.

        Args:
            root (str | Path): staged fileとfinalized blobを置くroot directory.
            read_chunk_size (int): 1回の ``read()`` に渡すbyte数.
        """
        self._root = Path(root)
        self._tmp_root = self._root / ".tmp"
        self._read_chunk_size = read_chunk_size

    async def validate_configuration(self) -> None:
        """root、staging、finalized blob directoryの作成可能性を検証する.

        Returns:
            None: 必要なdirectoryが存在し、rootとfinalized blob directoryへ書き込める状態にする.

        Raises:
            BlobStorageConfigurationError: directoryの作成、種別、または書き込みprobeが
                失敗した場合.
        """
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
        """一時directoryにstaged writeを開始する.

        Returns:
            StagedBlobWrite: finalizeまたはdiscardされるまで読み出せないstaged write.

        Raises:
            BlobStorageConfigurationError: backend directoryの検証に失敗した場合.
            BackendWriteError: staging fileの作成に失敗した場合.
        """
        await self.validate_configuration()
        try:
            return _LocalStagedBlobWrite(
                root=self._root,
                stage_path=self._create_stage_path(),
            )
        except OSError as exc:
            raise BackendWriteError("failed to create local blob staging file") from exc

    async def open_read(self, storage_key: str) -> ByteChunks:
        """Finalized blobのbytesを返す非同期chunk iteratorを開く.

        Args:
            storage_key (str): ``sha256/xx/yy/<digest>`` 形式の保存key.

        Returns:
            ByteChunks: 設定済みread sizeでblob内容を返す非同期iterator.

        Raises:
            BlobContentMissingError: keyが不正、blobが未存在、directory、またはsymbolic linkの場合.
            BackendReadError: iteratorによるblob読取中にfilesystem errorが発生した場合.
        """
        path = _final_path_for_read(self._root, storage_key)
        if path is None or not _is_finalized_file(path):
            raise BlobContentMissingError(storage_key)

        async def chunks() -> AsyncIterator[bytes]:
            """開いたfinalized blobを同期filesystemから非同期iteratorとして読み出す.

            Yields:
                bytes: filesystemから読み込んだ連続したblob内容.

            Raises:
                BlobContentMissingError: iterator開始後にblobが削除された場合.
                BackendReadError: blob読取中にfilesystem errorが発生した場合.
            """
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
        """保存keyに対応するfinalized regular fileが存在するか確認する.

        Args:
            storage_key (str): ``sha256/xx/yy/<digest>`` 形式の保存key.

        Returns:
            bool: keyが正しく、root配下にsymbolic linkではないregular fileがある場合は ``True``.
        """
        path = _final_path_for_read(self._root, storage_key)
        return path is not None and _is_finalized_file(path)

    def _create_stage_path(self) -> Path:
        """一時directory内に空の一意な.part fileを作成する.

        Returns:
            Path: 作成済みの空のstaging fileへのpath.

        Raises:
            OSError: temporary fileの作成またはfile descriptorのcloseに失敗した場合.
        """
        file_descriptor, path = tempfile.mkstemp(
            prefix="blob-",
            suffix=".part",
            dir=self._tmp_root,
        )
        os.close(file_descriptor)
        return Path(path)

    def _validate_final_storage_directory(self) -> None:
        """確定済みSHA-256階層へ安全に書き込めるかprobeする.

        Returns:
            None: probe directoryとtemporary probe fileを検証後に削除する.

        Raises:
            BlobStorageConfigurationError: finalized pathの作成、種別、または書き込みprobeが
                失敗した場合.
        """
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
    """ローカルbackendの未公開staged writeを管理する.

    Attributes:
        _root (Path): finalized blobを保存するbackend root.
        _stage_path (Path): 未公開のstaging file path.
        _closed (bool): finalizeまたはdiscard済みであることを表す状態.
    """

    _root: Path
    _stage_path: Path
    _closed: bool

    def __init__(self, *, root: Path, stage_path: Path) -> None:
        """一時fileとfinalized blob rootを保持する.

        Args:
            root (Path): finalized blobを保存するbackend root.
            stage_path (Path): ``begin_write`` が作成したstaging file path.
        """
        self._root = root
        self._stage_path = stage_path
        self._closed = False

    async def write(self, chunk: bytes) -> None:
        """バイト列をstaging file末尾へ追記する.

        Args:
            chunk (bytes): staged blobへ追加する内容.

        Returns:
            None: chunkを書き込む. 失敗時はstaging fileを破棄してclosed状態にする.

        Raises:
            BackendWriteError: closed済み、またはstaging fileへの追記に失敗した場合.
        """
        self._ensure_open()
        try:
            with self._stage_path.open("ab") as staged_file:
                _ = staged_file.write(chunk)
        except OSError as exc:
            self._discard_without_error()
            self._closed = True
            raise BackendWriteError("failed to write local blob staging content") from exc

    async def finalize(self, storage_key: str) -> None:
        """一時保存したbytesをSHA-256由来のfinal keyへatomicに公開する.

        Args:
            storage_key (str): ``sha256/xx/yy/<digest>`` 形式の公開先key.

        Returns:
            None: staging fileを破棄し、同じkeyのfinalized fileを公開済みにする.

        Raises:
            BackendWriteError: closed済み、不正key、root外path、既存の不正file、または公開処理に
                失敗した場合.

        Notes:
            同じkeyにregular finalized fileが既にある場合は成功としてstaging fileだけを破棄する.
        """
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
        """最終contentを公開せずにstaging fileを破棄する.

        Returns:
            None: staging fileを削除してclosed状態にする. 既にclosedなら何もしない.

        Raises:
            BackendWriteError: staging fileの削除に失敗した場合.
        """
        if self._closed:
            return
        try:
            self._stage_path.unlink(missing_ok=True)
        except OSError as exc:
            raise BackendWriteError("failed to discard local blob staging content") from exc
        finally:
            self._closed = True

    def _ensure_open(self) -> None:
        """一時writeがまだfinalizeまたはdiscardされていないことを確認する.

        Returns:
            None: staged writeがopenのままであることを確認する.

        Raises:
            BackendWriteError: staged writeがすでにclosedの場合.
        """
        if self._closed:
            raise BackendWriteError("local blob staging write is already closed")

    def _discard_without_error(self) -> None:
        """一時fileを削除し、cleanup時のfilesystem errorを無視する.

        Returns:
            None: staging fileの削除を試みる. filesystem errorは呼出元へ伝播しない.
        """
        with suppress(OSError):
            self._stage_path.unlink(missing_ok=True)


def _final_path_for_read(root: Path, storage_key: str) -> Path | None:
    """読み出し可能なstorage keyから候補final pathを組み立てる.

    Args:
        root (Path): blob storageのroot directory.
        storage_key (str): ``sha256/xx/yy/<digest>`` 形式の保存key.

    Returns:
        Path | None: root配下の候補path. 不正keyまたはroot外へ解決されるpathなら ``None``.
    """
    digest = _storage_key_digest(storage_key)
    if digest is None:
        return None

    final_path = root / "sha256" / digest[:2] / digest[2:4] / digest
    if not _is_under_root(root, final_path):
        return None
    return final_path


def _final_path_for_write(root: Path, storage_key: str) -> Path:
    """書き込み用storage keyからroot配下のfinal pathを組み立てる.

    Args:
        root (Path): blob storageのroot directory.
        storage_key (str): ``sha256/xx/yy/<digest>`` 形式の保存key.

    Returns:
        Path: root配下で検証済みのfinalized blob path.

    Raises:
        BackendWriteError: keyがSHA-256形式でない場合、またはpathがroot外へ解決される場合.
    """
    digest = _storage_key_digest(storage_key)
    if digest is None:
        raise BackendWriteError(f"invalid SHA-256 storage key: {storage_key}")

    final_path = root / "sha256" / digest[:2] / digest[2:4] / digest
    _ensure_under_root(root, final_path)
    return final_path


def _storage_key_digest(storage_key: str) -> str | None:
    """保存keyから検証済みのlowercase SHA-256 digestを取り出す.

    Args:
        storage_key (str): ``sha256/xx/yy/<64桁hex>`` 形式であることが期待されるkey.

    Returns:
        str | None: 64桁digest. 形式、hex文字、またはdirectory prefixが一致しない場合は ``None``.
    """
    match = _SHA256_STORAGE_KEY_PATTERN.fullmatch(storage_key)
    if match is None:
        return None

    first_prefix, second_prefix, digest = match.groups()
    if first_prefix != digest[:2] or second_prefix != digest[2:4]:
        return None
    return digest


def _ensure_under_root(root: Path, path: Path) -> None:
    """候補pathがroot directoryの内側へ解決されることを検証する.

    Args:
        root (Path): 許可するfilesystem root.
        path (Path): root配下であるべき候補path.

    Returns:
        None: pathがroot配下であることを確認する.

    Raises:
        BackendWriteError: pathがroot外へ解決される場合.
    """
    if not _is_under_root(root, path):
        raise BackendWriteError(f"local blob path escapes storage root: {path}")


def _ensure_existing_finalized_file(path: Path, storage_key: str) -> None:
    """既存final pathがsymbolic linkではないregular fileか検証する.

    Args:
        path (Path): 検証する既存final path.
        storage_key (str): error messageへ記録する保存key.

    Returns:
        None: pathがfinalized regular fileであることを確認する.

    Raises:
        BackendWriteError: pathがregular fileでない、またはsymbolic linkの場合.
    """
    if not _is_finalized_file(path):
        raise BackendWriteError(f"local blob final path is not a file: {storage_key}")


def _is_finalized_file(path: Path) -> bool:
    """候補pathがsymbolic linkではないregular fileか判定する.

    Args:
        path (Path): 判定対象のfilesystem path.

    Returns:
        bool: regular fileでありsymbolic linkではない場合は ``True``.
    """
    return path.is_file() and not path.is_symlink()


def _ensure_probe_directory(path: Path) -> None:
    """検証用pathがdirectoryであることを確認する.

    Args:
        path (Path): configuration validationで使うprobe directory.

    Returns:
        None: pathがdirectoryであることを確認する.

    Raises:
        BlobStorageConfigurationError: pathがdirectoryでない場合.
    """
    if not path.is_dir():
        raise BlobStorageConfigurationError(
            f"local blob storage final path is not a directory: {path}",
        )


def _is_under_root(root: Path, path: Path) -> bool:
    """候補pathが解決後もroot directory配下にあるか判定する.

    Args:
        root (Path): 許可するfilesystem root.
        path (Path): root配下か検証する候補path.

    Returns:
        bool: strictではないpath解決後にpathがrootのrelative pathになる場合は ``True``.
    """
    try:
        _ = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True
