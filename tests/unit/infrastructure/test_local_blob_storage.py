"""Local blob storageのconfigurationとstaging/finalization安全性を検証する."""

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
    """ContentのSHA-256 digestからcanonical storage keyを生成する.

    Args:
        content (bytes): key計算に使うblob content.

    Returns:
        str: sha256 prefixと2段shardを持つcanonical key.
    """
    digest = hashlib.sha256(content).hexdigest()
    return f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"


def final_storage_path(root: Path, content: bytes) -> Path:
    """Contentのcanonical storage keyに対応する最終filesystem pathを生成する.

    Args:
        root (Path): local blob storageのroot directory.
        content (bytes): digestとshard path計算に使うblob content.

    Returns:
        Path: root配下のcanonical final blob path.
    """
    digest = hashlib.sha256(content).hexdigest()
    return root / "sha256" / digest[:2] / digest[2:4] / digest


async def collect_chunks(chunks: AsyncIterator[bytes]) -> bytes:
    """Async byte streamを結合してassertion用contentへ変換する.

    Args:
        chunks (AsyncIterator[bytes]): backend readが返す順序付きbyte stream.

    Returns:
        bytes: 全chunkを結合したcontent.
    """
    return b"".join([chunk async for chunk in chunks])


async def test_validate_configuration_creates_missing_writable_root(tmp_path: Path) -> None:
    """Missing writable rootをconfiguration validationが作成する契約を検証する.

    存在しない一時rootでlocal backendを検証する.
    rootがdirectoryとなりstaged write開始が可能になることを確認する.

    Args:
        tmp_path (Path): backend rootに使うpytest一時directory.

    Returns:
        None: writable root作成を検証して完了し値を返さない.
    """
    root = tmp_path / "blob-root"
    backend = LocalBlobStorageBackend(root)

    await backend.validate_configuration()

    assert root.is_dir()
    staged = await backend.begin_write()
    await staged.write(b"writable")
    await staged.discard()


async def test_validate_configuration_uses_collision_safe_final_probe_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configuration probeが固定path衝突を回避する契約を検証する.

    固定名probeを削除するPath.write_bytes overrideでbackendを検証する.
    collision-safeなfinal probe pathを使うためvalidationが成功することを確認する.

    Args:
        tmp_path (Path): backend rootとPath monkeypatch対象に使う一時directory.
        monkeypatch (pytest.MonkeyPatch): fixed probe挙動を再現するpytest patch helper.

    Returns:
        None: collision-safe probe動作を検証して完了し値を返さない.
    """
    original_write_bytes = type(tmp_path).write_bytes

    def delete_fixed_probe_after_write(path: Path, data: bytes) -> int:
        """固定名probeのwrite後にfileを削除するtest doubleを実行する.

        Args:
            path (Path): write対象となるPath instance.
            data (bytes): Path.write_bytesへ渡されるprobe content.

        Returns:
            int: 元のwrite_bytesが書き込んだbyte数.
        """
        written = original_write_bytes(path, data)
        if path.name == ".probe":
            path.unlink()
        return written

    monkeypatch.setattr(type(tmp_path), "write_bytes", delete_fixed_probe_after_write)
    backend = LocalBlobStorageBackend(tmp_path)

    await backend.validate_configuration()


async def test_validate_configuration_rejects_file_root(tmp_path: Path) -> None:
    """Fileをrootに指定したconfigurationを拒否する契約を検証する.

    directoryではない一時fileをlocal backend rootとして検証する.
    BlobStorageConfigurationErrorが送出されることを確認する.

    Args:
        tmp_path (Path): file rootを作るpytest一時directory.

    Returns:
        None: invalid file root拒否を検証して完了し値を返さない.
    """
    root = tmp_path / "not-a-directory"
    _ = root.write_text("not a directory", encoding="utf-8")
    backend = LocalBlobStorageBackend(root)

    with pytest.raises(BlobStorageConfigurationError):
        await backend.validate_configuration()


async def test_validate_configuration_rejects_uncreatable_final_storage_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final storage directoryを作れないconfigurationを拒否する契約を検証する.

    final shard directory作成だけを失敗させるPath.mkdir overrideでbackendを検証する.
    BlobStorageConfigurationErrorが送出されることを確認する.

    Args:
        tmp_path (Path): blocked final pathを構成するpytest一時directory.
        monkeypatch (pytest.MonkeyPatch): mkdir failureを注入するpytest patch helper.

    Returns:
        None: uncreatable final path拒否を検証して完了し値を返さない.
    """
    original_mkdir = type(tmp_path).mkdir
    blocked_final_directory = tmp_path / "sha256" / "00" / "00"

    def fail_final_storage_mkdir(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        """指定final directoryだけを作成不能にするPath.mkdir test doubleを実行する.

        Args:
            path (Path): mkdir対象となるPath instance.
            mode (int): 元のmkdirへ渡すpermission mode.
            parents (bool): parent directory作成を許可するかを示すflag.
            exist_ok (bool): 既存directoryを許可するかを示すflag.

        Returns:
            None: 元のmkdirへ委譲するかOSErrorを送出して完了する.

        Raises:
            OSError: blocked final directoryの作成が要求された場合.
        """
        if path == blocked_final_directory:
            raise OSError("final storage directory cannot be created")
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(type(tmp_path), "mkdir", fail_final_storage_mkdir)
    backend = LocalBlobStorageBackend(tmp_path)

    with pytest.raises(BlobStorageConfigurationError):
        await backend.validate_configuration()


async def test_staged_content_becomes_readable_only_after_finalize(tmp_path: Path) -> None:
    """Staged contentがfinalize前にread可能にならない契約を検証する.

    複数chunkを書いたstaged blobをfinalize前後でexistsとopen_readする.
    finalize後だけcontentが存在し完全なbyte列を読めることを確認する.

    Args:
        tmp_path (Path): local backend rootに使うpytest一時directory.

    Returns:
        None: staging isolationとfinalization公開を検証して完了し値を返さない.
    """
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
    """Finalized contentをconfigured backend chunk sizeでstreamする契約を検証する.

    chunk size 4のbackendへcontentをfinalizeしてopen_readする.
    streamが4 byte単位の順序付きchunkを返すことを確認する.

    Args:
        tmp_path (Path): local backend rootに使うpytest一時directory.

    Returns:
        None: backend chunk streamingを検証して完了し値を返さない.
    """
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
    """未finalizeのvalid storage keyをmissing contentとして扱う契約を検証する.

    digest形式のkeyを作るがcontentを書かずにexistsとopen_readする.
    existsがFalseでBlobContentMissingErrorが同じkeyを保持することを確認する.

    Args:
        tmp_path (Path): local backend rootに使うpytest一時directory.

    Returns:
        None: missing valid key処理を検証して完了し値を返さない.
    """
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
    """User filename風keyをfilesystem pathとして読まない契約を検証する.

    root直下にavatar fileを置いてfilename keyでexistsとopen_readする.
    contentがmissingとして扱われfilename keyがerrorへ保持されることを確認する.

    Args:
        tmp_path (Path): filename fileとbackend rootを持つpytest一時directory.

    Returns:
        None: user filename path拒否を検証して完了し値を返さない.
    """
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
    """Path traversal風keyをroot外pathとして読まない契約を検証する.

    backend root外にfileを置いてparent traversal keyでexistsとopen_readする.
    contentがmissingとして扱われtraversal keyがerrorへ保持されることを確認する.

    Args:
        tmp_path (Path): root外fileとbackend rootを持つpytest一時directory.

    Returns:
        None: root外read拒否を検証して完了し値を返さない.
    """
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
    """同じfinal keyへの2回目finalizeが既存contentを上書きしない契約を検証する.

    最初のcontentをfinalize後に異なるstaged contentを同じkeyへfinalizeする.
    original contentが保持されtemporary staging fileが残らないことを確認する.

    Args:
        tmp_path (Path): local backend rootに使うpytest一時directory.

    Returns:
        None: idempotent finalizationを検証して完了し値を返さない.
    """
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
    """Final pathにdirectoryがある場合にfinalizeを拒否する契約を検証する.

    canonical final pathをdirectoryとして先に作りstaged contentをfinalizeする.
    BackendWriteErrorが送出されdirectory保持とcontent非公開を確認する.

    Args:
        tmp_path (Path): final directoryとbackend rootに使うpytest一時directory.

    Returns:
        None: directory collision拒否を検証して完了し値を返さない.
    """
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
    """Final pathにsymlinkがある場合にfinalizeを拒否する契約を検証する.

    canonical final pathへ別fileを指すsymlinkを作りstaged contentをfinalizeする.
    BackendWriteErrorが送出されsymlink保持とcontent非公開を確認する.

    Args:
        tmp_path (Path): symlinkとbackend rootに使うpytest一時directory.

    Returns:
        None: symlink collision拒否を検証して完了し値を返さない.
    """
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
    """Link時raceでfinal pathがdirectoryになる場合にfinalizeを拒否する契約を検証する.

    os.linkがdirectoryを作ってFileExistsErrorを送出するraceを注入してfinalizeする.
    BackendWriteError後もdirectoryが残りcontentとtemporary fileが公開されないことを確認する.

    Args:
        tmp_path (Path): final pathとbackend rootに使うpytest一時directory.
        monkeypatch (pytest.MonkeyPatch): link raceを注入するpytest patch helper.

    Returns:
        None: non-file final path race拒否を検証して完了し値を返さない.
    """
    backend = LocalBlobStorageBackend(tmp_path)
    await backend.validate_configuration()
    content = b"file exists race"
    storage_key = sha256_storage_key(content)
    final_path = final_storage_path(tmp_path, content)
    final_path.parent.mkdir(parents=True, exist_ok=True)

    def create_directory_then_raise(src: object, dst: object) -> None:
        """Final pathをdirectoryへ競合させてFileExistsErrorを送出するtest doubleを実行する.

        Args:
            src (object): os.linkが渡すstaged source path.
            dst (object): os.linkが渡すfinal destination path.

        Returns:
            None: directory作成後にexceptionを送出して完了する.

        Raises:
            AssertionError: 想定外のfinal destinationが渡された場合.
            FileExistsError: final path raceを再現する場合.
        """
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
    """Staging write失敗がfinal blobを公開しない契約を検証する.

    write開始後にtemporary staging rootを削除してchunkを書き込む.
    BackendWriteError後もfinal keyがmissingとして扱われることを確認する.

    Args:
        tmp_path (Path): temporary staging rootとbackend rootに使うpytest一時directory.

    Returns:
        None: failed staging write隔離を検証して完了し値を返さない.
    """
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
    """SHA-256形式でないfinal keyを拒否してblobを公開しない契約を検証する.

    traversalとuppercase digestとshard mismatchのkeyでstaged contentをfinalizeする.
    各BackendWriteError後にtemporary fileとvalid keyのcontentが存在しないことを確認する.

    Args:
        tmp_path (Path): local backend rootに使うpytest一時directory.

    Returns:
        None: invalid final key拒否を検証して完了し値を返さない.
    """
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
    """Discardしたstaged contentをfinal blobとして公開しない契約を検証する.

    contentを書いたstaged writeをfinalizeせずdiscardする.
    final keyが存在せずopen_readがmissing errorとなることを確認する.

    Args:
        tmp_path (Path): local backend rootに使うpytest一時directory.

    Returns:
        None: discarded staging隔離を検証して完了し値を返さない.
    """
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
