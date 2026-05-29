"""Structured logging initialization using structlog + stdlib integration.

Configures dual output (console + optional JSON file) with a shared processor chain.
All stdlib loggers (including uvicorn) are routed through structlog's ProcessorFormatter.
"""

from __future__ import annotations

import gzip
import logging
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

try:
    import fcntl
except ImportError:
    fcntl = None

import structlog
import structlog.contextvars
import structlog.processors
import structlog.stdlib
import structlog.types

if TYPE_CHECKING:
    from osu_server.config import AppConfig

_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "password_md5",
    }
)


@dataclass(slots=True)
class _LoggingSessionLock:
    file: TextIO | None = None
    path: Path | None = None


_SESSION_LOCK = _LoggingSessionLock()


def mask_sensitive_fields(
    _logger: structlog.types.WrappedLogger,  # pyright: ignore[reportAny]
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Replace sensitive field values with '***' to prevent credential leakage."""
    for key in _SENSITIVE_KEYS:
        if key in event_dict:
            event_dict[key] = "***"
    return event_dict


def _archive_latest_file(latest_path: Path, log_dir: Path) -> None:
    """latest.jsonl を日付ベースのファイルに圧縮アーカイブし、元ファイルを削除する。"""
    today_str = datetime.now().astimezone().date().isoformat()
    max_n = 0
    for p in log_dir.glob(f"{today_str}-*.jsonl.gz"):
        name = p.name
        if name.endswith(".jsonl.gz"):
            stem = name[:-9]  # len(".jsonl.gz") == 9
            try:
                n_str = stem.split("-")[-1]
                n = int(n_str)
                max_n = max(max_n, n)
            except (ValueError, IndexError):
                pass

    archive_name = f"{today_str}-{max_n + 1}.jsonl.gz"
    archive_path = log_dir / archive_name

    # 圧縮アーカイブの作成
    with latest_path.open("rb") as f_in, gzip.open(archive_path, "wb") as f_out:
        while chunk := f_in.read(65536):
            _ = f_out.write(chunk)

    # 元ファイルの削除
    latest_path.unlink()


def _cleanup_old_archives(log_dir: Path, max_files: int) -> None:
    """古いアーカイブを削除する。"""
    archives: list[tuple[float, Path]] = []
    for p in log_dir.glob("*.jsonl.gz"):
        try:
            mtime = p.stat().st_mtime
            archives.append((mtime, p))
        except OSError as exc:
            warnings.warn(
                f"Failed to stat archive file {p}: {exc}",
                category=UserWarning,
                stacklevel=1,
            )

    # mtime でソート (古いもの = 小さい mtime が先頭)
    archives.sort(key=lambda x: x[0])

    if len(archives) > max_files:
        to_delete = archives[: len(archives) - max_files]
        for _, p in to_delete:
            try:
                _ = p.unlink()
            except OSError as exc:
                warnings.warn(
                    f"Failed to delete old archive file {p}: {exc}",
                    category=UserWarning,
                    stacklevel=1,
                )


def _open_logging_session_lock(log_dir: Path, lock_path: Path) -> TextIO | None:
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        return lock_path.open("a")
    except OSError as exc:
        warnings.warn(
            f"Failed to open logging session lock {lock_path}: {exc}",
            category=UserWarning,
            stacklevel=1,
        )
        return None


def _acquire_existing_logging_session(lock_file: TextIO, lock_path: Path) -> bool:
    if fcntl is None:
        return False

    try:
        fcntl.flock(lock_file, fcntl.LOCK_SH)
    except OSError as exc:
        warnings.warn(
            f"Failed to acquire logging session lock {lock_path}: {exc}",
            category=UserWarning,
            stacklevel=1,
        )
        return False
    return True


def _prepare_process_logging_session(log_dir: Path) -> bool:
    """Return True only for the first active process using this log directory."""
    lock_path = log_dir / ".session.lock"
    if _SESSION_LOCK.path == lock_path and _SESSION_LOCK.file is not None:
        return False

    if _SESSION_LOCK.file is not None:
        _SESSION_LOCK.file.close()
        _SESSION_LOCK.file = None
        _SESSION_LOCK.path = None

    if fcntl is None:
        return True

    lock_file = _open_logging_session_lock(log_dir, lock_path)
    if lock_file is None:
        return False

    should_rotate = True
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        should_rotate = False
        if not _acquire_existing_logging_session(lock_file, lock_path):
            lock_file.close()
            return False
    except OSError as exc:
        lock_file.close()
        warnings.warn(
            f"Failed to acquire logging session lock {lock_path}: {exc}",
            category=UserWarning,
            stacklevel=1,
        )
        return False

    _SESSION_LOCK.file = lock_file
    _SESSION_LOCK.path = lock_path
    return should_rotate


def _downgrade_process_logging_session() -> None:
    """Keep a shared lock so later processes know this log session is active."""
    if fcntl is None or _SESSION_LOCK.file is None or _SESSION_LOCK.path is None:
        return

    try:
        fcntl.flock(_SESSION_LOCK.file, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError as exc:
        warnings.warn(
            f"Failed to downgrade logging session lock {_SESSION_LOCK.path}: {exc}",
            category=UserWarning,
            stacklevel=1,
        )


def rotate_logs(log_dir: Path, max_files: int) -> None:
    """起動時にログファイルをアーカイブし、古いアーカイブを削除する。

    1. latest.jsonl が存在し非空なら、ファイルロック取得を試みる
    2. ロック取得成功: latest.jsonl を {date}-{N}.jsonl.gz にアーカイブ
    3. アーカイブ数が max_files を超えたら古い順に削除
    4. ロック取得失敗 or ファイル不在/空: スキップ
    5. 全ての OSError は warnings.warn で警告して続行
    """
    latest_path = log_dir / "latest.jsonl"
    try:
        if not latest_path.exists() or latest_path.stat().st_size == 0:
            return
    except OSError as exc:
        warnings.warn(
            f"Failed to check log file {latest_path}: {exc}",
            category=UserWarning,
            stacklevel=1,
        )
        return

    lock_path = log_dir / ".rotation.lock"
    try:
        with lock_path.open("a") as f_lock:
            try:
                if fcntl is not None:
                    fcntl.flock(f_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            except OSError as exc:
                warnings.warn(
                    f"Failed to acquire lock on {lock_path}: {exc}",
                    category=UserWarning,
                    stacklevel=1,
                )
                return

            try:
                _archive_latest_file(latest_path, log_dir)
                _cleanup_old_archives(log_dir, max_files)
            except OSError as exc:
                warnings.warn(
                    f"Failed to archive log file {latest_path}: {exc}",
                    category=UserWarning,
                    stacklevel=1,
                )
    except OSError as exc:
        warnings.warn(
            f"Failed to open lock file {lock_path}: {exc}",
            category=UserWarning,
            stacklevel=1,
        )


def setup_logging(config: AppConfig) -> None:
    """Initialize structlog with stdlib integration and configure output handlers.

    - Calls rotate_logs(Path(config.log_dir), config.log_max_files) once per
      active multi-process logging session.
    - Console output (ConsoleRenderer) is always enabled via StreamHandler(stderr).
    - A FileHandler with JSONRenderer is always added to config.log_dir / "latest.jsonl".
    - config.log_level controls the root logger level.
    - uvicorn.error and uvicorn.access logger handlers are overridden with
      structlog ProcessorFormatter.
    """
    # 起動時ローテーションの実行
    log_dir_path = Path(config.log_dir)
    if _prepare_process_logging_session(log_dir_path):
        try:
            rotate_logs(log_dir_path, config.log_max_files)
        finally:
            _downgrade_process_logging_session()

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        mask_sensitive_fields,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    # --- Console handler (always active) ---
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(),
        foreign_pre_chain=shared_processors,
    )
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(console_formatter)

    # --- JSON file handler (always active) ---
    json_handler: logging.FileHandler | None = None
    json_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )
    log_path = log_dir_path / "latest.jsonl"
    try:
        log_dir_path.mkdir(parents=True, exist_ok=True)
        json_handler = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
        json_handler.setFormatter(json_formatter)
    except OSError as exc:
        warnings.warn(
            f"Failed to open JSON log file {log_path}: {exc}",
            stacklevel=1,
        )

    # --- Root logger setup ---
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(config.log_level)
    root_logger.addHandler(console_handler)
    if json_handler is not None:
        root_logger.addHandler(json_handler)

    # --- Override uvicorn logger handlers ---
    _override_uvicorn_handlers(console_handler, json_handler)

    # --- Log current configuration ---
    structlog.get_logger().info(  # pyright: ignore[reportAny]
        "logging_configured",
        log_level=config.log_level,
        log_dir=config.log_dir,
        log_max_files=config.log_max_files,
    )


def _override_uvicorn_handlers(
    console_handler: logging.Handler,
    json_handler: logging.Handler | None,
) -> None:
    """Replace uvicorn logger handlers so their output goes through structlog."""
    for logger_name in ("uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.addHandler(console_handler)
        if json_handler is not None:
            uvicorn_logger.addHandler(json_handler)
        uvicorn_logger.propagate = False
