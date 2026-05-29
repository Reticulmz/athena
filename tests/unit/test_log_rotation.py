"""Unit tests for the log rotation logic."""

from __future__ import annotations

import gzip
import warnings
from datetime import date
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
    latest.write_bytes(content)
    
    today_str = date.today().isoformat()
    
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
    today_str = date.today().isoformat()
    
    # 既存のアーカイブを模擬
    (tmp_path / f"{today_str}-1.jsonl.gz").touch()
    (tmp_path / f"{today_str}-2.jsonl.gz").touch()
    
    latest = tmp_path / "latest.jsonl"
    content = b'{"event": "another test"}\n'
    latest.write_bytes(content)
    
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
    latest.write_bytes(content)
    
    # gzip.open で OSError を発生させる
    with patch("gzip.open", side_effect=OSError("Disk Full")):
        with pytest.warns(UserWarning, match="Failed to archive log file"):
            rotate_logs(tmp_path, max_files=30)
            
    # 元ファイルが削除されずに残っていることを検証
    assert latest.exists()
    assert latest.read_bytes() == content
