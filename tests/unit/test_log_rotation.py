"""Unit tests for the log rotation logic."""

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
    """latest.jsonl が存在しない場合、ローテーションはスキップされる."""
    rotate_logs(tmp_path, max_files=30)

    # アーカイブファイルが生成されていないことを検証
    archives = list(tmp_path.glob("*.jsonl.gz"))
    assert not archives


def test_rotate_logs_empty_file(tmp_path: Path) -> None:
    """latest.jsonl が空 (0バイト) の場合、ローテーションはスキップされる."""
    latest = tmp_path / "latest.jsonl"
    latest.touch()

    rotate_logs(tmp_path, max_files=30)

    # アーカイブファイルが生成されておらず、latest.jsonl も残っていることを検証
    archives = list(tmp_path.glob("*.jsonl.gz"))
    assert not archives
    assert latest.exists()


def test_rotate_logs_success(tmp_path: Path) -> None:
    """latest.jsonl が非空の場合、日付-1.jsonl.gz にアーカイブされ、元ファイルは削除される."""
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
    """既存の同日アーカイブがある場合、連番がインクリメントされる."""
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
    """OSError 発生時に例外を伝播せず warnings.warn で警告し、latest.jsonl を残す."""
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
    """別のプロセスがロックを保持している場合、ローテーションをスキップ.

    latest.jsonl を残す(警告は出ない).
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
    """max_files 超過時に、mtime が最も古いアーカイブファイルが削除される.

    最新の max_files 件のみが残る.
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
    """古いアーカイブの削除時に OSError が発生した場合、警告を出力して続行する."""
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

    def side_effect(self: Path, missing_ok: bool = False) -> None:
        if self.name == "latest.jsonl":
            original_unlink(self, missing_ok=missing_ok)
            return
        raise OSError("Permission Denied")

    with (
        patch.object(Path, "unlink", side_effect),
        pytest.warns(UserWarning, match="Failed to delete old archive file"),
    ):
        rotate_logs(tmp_path, max_files=1)
