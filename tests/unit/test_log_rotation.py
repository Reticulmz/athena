"""log rotationの正常系と障害時の保存契約を検証する."""

from __future__ import annotations

import fcntl
import gzip
import os
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from osu_server.infrastructure.logging import rotate_logs


def test_rotate_logs_no_file(tmp_path: Path) -> None:
    """latest.jsonlがない場合にarchiveを作らず完了する契約を検証する.

    空のlog directoryでrotate_logsを実行し,圧縮archiveが生成されないことを確認する.

    Args:
        tmp_path (Path): test専用の空log directory.

    Returns:
        None: archive不在を検証して完了し,呼び出し側へ値を返さない.
    """
    rotate_logs(tmp_path, max_files=30)

    # アーカイブファイルが生成されていないことを検証
    archives = list(tmp_path.glob("*.jsonl.gz"))
    assert not archives


def test_rotate_logs_empty_file(tmp_path: Path) -> None:
    """空のlatest.jsonlをarchiveせず保持する契約を検証する.

    0 byteのlatest.jsonlでrotate_logsを実行し,archiveがなく元fileが残ることを確認する.

    Args:
        tmp_path (Path): 空fileを作成するtest専用log directory.

    Returns:
        None: 空fileの無変更を検証して完了し,呼び出し側へ値を返さない.
    """
    latest = tmp_path / "latest.jsonl"
    latest.touch()

    rotate_logs(tmp_path, max_files=30)

    # アーカイブファイルが生成されておらず、latest.jsonl も残っていることを検証
    archives = list(tmp_path.glob("*.jsonl.gz"))
    assert not archives
    assert latest.exists()


def test_rotate_logs_success(tmp_path: Path) -> None:
    """非空latest.jsonlを日付付きgzip archiveへ移す契約を検証する.

    log内容を持つlatest.jsonlでrotate_logsを実行し,元fileが消えて日付-1.jsonl.gzの復元内容が一致することを確認する.

    Args:
        tmp_path (Path): source logとarchiveを保持するtest専用directory.

    Returns:
        None: archiveの内容と元file削除を検証して完了し,呼び出し側へ値を返さない.
    """
    latest = tmp_path / "latest.jsonl"
    content = b'{"event": "test", "level": "info"}\n'
    _ = latest.write_bytes(content)

    today_str = datetime.now(UTC).astimezone().date().isoformat()

    rotate_logs(tmp_path, max_files=30)

    # 元ファイルが削除されていることを検証
    assert not latest.exists()

    # アーカイブファイルを検証
    archive_path = tmp_path / f"{today_str}-1.jsonl.gz"
    assert archive_path.exists()

    # gzip解凍して内容が一致することを検証
    with gzip.open(archive_path, "rb") as f:
        archived_content = f.read()
    assert archived_content == content


def test_rotate_logs_increment(tmp_path: Path) -> None:
    """同日archiveがある場合に次の連番を選ぶ契約を検証する.

    -1と-2 archiveを用意してrotate_logsを実行し,新しい内容が-3 archiveへ保存されることを確認する.

    Args:
        tmp_path (Path): 同日archiveとsource logを保持するtest専用directory.

    Returns:
        None: 連番の増加とarchive内容を検証して完了し,呼び出し側へ値を返さない.
    """
    today_str = datetime.now(UTC).astimezone().date().isoformat()

    # 既存のアーカイブを模擬
    (tmp_path / f"{today_str}-1.jsonl.gz").touch()
    (tmp_path / f"{today_str}-2.jsonl.gz").touch()

    latest = tmp_path / "latest.jsonl"
    content = b'{"event": "another test"}\n'
    _ = latest.write_bytes(content)

    rotate_logs(tmp_path, max_files=30)

    # 元ファイルが削除されていることを検証
    assert not latest.exists()

    # 新しいアーカイブ {today}-3.jsonl.gz が生成されていることを検証
    archive_path = tmp_path / f"{today_str}-3.jsonl.gz"
    assert archive_path.exists()

    # 内容の検証
    with gzip.open(archive_path, "rb") as f:
        archived_content = f.read()
    assert archived_content == content


def test_rotate_logs_os_error(tmp_path: Path) -> None:
    """archive中のOSErrorをwarningへ変換してsource logを残す契約を検証する.

    gzip.openをOSErrorに差し替えてrotate_logsを実行し,UserWarningが出てlatest.jsonlの内容が維持されることを確認する.

    Args:
        tmp_path (Path): source logを作成するtest専用directory.

    Returns:
        None: warningとsource logの保持を検証して完了し,呼び出し側へ値を返さない.
    """
    latest = tmp_path / "latest.jsonl"
    content = b'{"event": "fail test"}\n'
    _ = latest.write_bytes(content)

    # gzip.open で OSError を発生させる
    with (
        patch("gzip.open", side_effect=OSError("Disk Full")),
        pytest.warns(UserWarning, match="Failed to archive log file"),
    ):
        rotate_logs(tmp_path, max_files=30)

    # 元ファイルが削除されずに残っていることを検証
    assert latest.exists()
    assert latest.read_bytes() == content


def test_rotate_logs_lock_failure(tmp_path: Path) -> None:
    """既存processがlockを保持する場合にwarningなしでrotationをskipする契約を検証する.

    lock fileへnonblocking exclusive lockを保持したままrotate_logsを実行する.
    warningがなくlatest.jsonlが保持されることを確認する.

    Args:
        tmp_path (Path): lock fileとsource logを保持するtest専用directory.

    Returns:
        None: lock競合時の無変更を検証して完了し,呼び出し側へ値を返さない.
    """
    latest = tmp_path / "latest.jsonl"
    content = b'{"event": "lock test"}\n'
    _ = latest.write_bytes(content)

    # 実際にロックファイルをロックしておく
    lock_path = tmp_path / ".rotation.lock"
    # ロックファイルを開いて排他ロックをかける
    with lock_path.open("w") as f_lock:
        fcntl.flock(f_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # この状態で rotate_logs を実行
        # warnings.warn が呼ばれない(正常系スキップである)ことを確認する
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            rotate_logs(tmp_path, max_files=30)

            # 警告が発生していないことを検証
            assert len(w) == 0

    # 元ファイルが削除されずに残っていることを検証
    assert latest.exists()
    assert latest.read_bytes() == content


def test_rotate_logs_cleanup_old_archives(tmp_path: Path) -> None:
    """archive数がmax_filesを超える場合に最古fileを削除する契約を検証する.

    mtimeの異なるarchive群と新しいlogを用意してrotationを実行し,最新2件だけが残ることを確認する.

    Args:
        tmp_path (Path): 既存archiveとsource logを保持するtest専用directory.

    Returns:
        None: 古いarchiveの削除と最新archiveの保持を検証して完了し,呼び出し側へ値を返さない.
    """
    # 既存のアーカイブを3個作成し、mtime をずらす
    archive1 = tmp_path / "2026-05-28-1.jsonl.gz"
    archive2 = tmp_path / "2026-05-28-2.jsonl.gz"
    archive3 = tmp_path / "2026-05-29-1.jsonl.gz"

    archive1.touch()
    archive2.touch()
    archive3.touch()

    # mtime を設定 (1が一番古く、3が一番新しい)
    now = time.time()
    os.utime(archive1, (now - 100, now - 100))
    os.utime(archive2, (now - 50, now - 50))
    os.utime(archive3, (now - 10, now - 10))

    # latest.jsonl がある状態で rotate_logs を実行
    latest = tmp_path / "latest.jsonl"
    _ = latest.write_bytes(b"some log data\n")

    # max_files=2 とするので、既存の3個 + 新しい1個 = 4個のうち、古い2個が削除されて最新の2個が残る
    rotate_logs(tmp_path, max_files=2)

    # 新しく生成されたファイルも含めた archives 一覧を確認
    archives = sorted(tmp_path.glob("*.jsonl.gz"), key=lambda p: p.stat().st_mtime)

    # 2件だけ残っていること
    assert len(archives) == 2

    # 最も古い2つ (archive1, archive2) が削除されていること
    assert not archive1.exists()
    assert not archive2.exists()

    # 新しい2つ (archive3 と 新規作成された今日の日付のアーカイブ) が残っていること
    assert archive3.exists()
    today_str = datetime.now(UTC).astimezone().date().isoformat()
    new_archive = tmp_path / f"{today_str}-1.jsonl.gz"
    assert new_archive.exists()


def test_rotate_logs_cleanup_os_error(tmp_path: Path) -> None:
    """古いarchive削除時のOSErrorをwarningへ変換して処理を続ける契約を検証する.

    archive unlinkだけをOSErrorにする差し替えでrotationを実行する.
    削除失敗のUserWarningが出ることを確認する.

    Args:
        tmp_path (Path): unlink対象archiveとsource logを保持するtest専用directory.

    Returns:
        None: cleanup失敗のwarningを検証して完了し,呼び出し側へ値を返さない.
    """
    archive1 = tmp_path / "2026-05-28-1.jsonl.gz"
    archive2 = tmp_path / "2026-05-28-2.jsonl.gz"

    archive1.touch()
    archive2.touch()

    now = time.time()
    os.utime(archive1, (now - 100, now - 100))
    os.utime(archive2, (now - 50, now - 50))

    latest = tmp_path / "latest.jsonl"
    _ = latest.write_bytes(b"some log data\n")

    # Path.unlink で OSError を発生させる
    # (latest.jsonl の削除は成功させるため、それ以外のみ raise する)
    original_unlink = Path.unlink

    def side_effect(path: Path, missing_ok: bool = False) -> None:
        """Source logだけを削除しarchive削除は失敗させるfakeを実行する.

        Args:
            path (Path): unlinkが要求された対象path.
            missing_ok (bool): Path.unlinkから渡される欠損許容設定.

        Returns:
            None: source logを削除するかOSErrorを送出して完了する.

        Raises:
            OSError: archive pathのunlinkを模擬的に拒否する場合.
        """
        if path.name == "latest.jsonl":
            original_unlink(path, missing_ok=missing_ok)
            return
        raise OSError("Permission Denied")

    with (
        patch.object(Path, "unlink", side_effect),
        pytest.warns(UserWarning, match="Failed to delete old archive file"),
    ):
        rotate_logs(tmp_path, max_files=1)
