"""Structured logging initialization using structlog + stdlib integration.

Configures dual output (console + optional JSON file) with a shared processor chain.
All stdlib loggers (including uvicorn) are routed through structlog's ProcessorFormatter.
"""

from __future__ import annotations

import gzip
import logging
import sys
import warnings
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

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


def rotate_logs(log_dir: Path, max_files: int) -> None:
    """起動時にログファイルをアーカイブし、古いアーカイブを削除する。

    1. latest.jsonl が存在し非空なら、ファイルロック取得を試みる
    2. ロック取得成功: latest.jsonl を {date}-{N}.jsonl.gz にアーカイブ
    3. アーカイブ数が max_files を超えたら古い順に削除
    4. ロック取得失敗 or ファイル不在/空: スキップ
    5. 全ての OSError は warnings.warn で警告して続行
    """
    import fcntl

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
        f_lock = open(lock_path, "a")
    except OSError as exc:
        warnings.warn(
            f"Failed to open lock file {lock_path}: {exc}",
            category=UserWarning,
            stacklevel=1,
        )
        return

    try:
        fcntl.flock(f_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        _ = f_lock.close()
        return
    except OSError as exc:
        warnings.warn(
            f"Failed to acquire lock on {lock_path}: {exc}",
            category=UserWarning,
            stacklevel=1,
        )
        _ = f_lock.close()
        return

    try:
        # アーカイブ名の決定
        today_str = date.today().isoformat()
        max_n = 0
        for p in log_dir.glob(f"{today_str}-*.jsonl.gz"):
            name = p.name
            if name.endswith(".jsonl.gz"):
                stem = name[:-9]  # len(".jsonl.gz") == 9
                try:
                    n_str = stem.split("-")[-1]
                    n = int(n_str)
                    if n > max_n:
                        max_n = n
                except (ValueError, IndexError):
                    pass

        archive_name = f"{today_str}-{max_n + 1}.jsonl.gz"
        archive_path = log_dir / archive_name

        # 圧縮アーカイブの作成
        with open(latest_path, "rb") as f_in, gzip.open(archive_path, "wb") as f_out:
            while chunk := f_in.read(65536):
                _ = f_out.write(chunk)

        # 元ファイルの削除
        latest_path.unlink()

    except OSError as exc:
        warnings.warn(
            f"Failed to archive log file {latest_path}: {exc}",
            category=UserWarning,
            stacklevel=1,
        )
        return
    finally:
        _ = f_lock.close()
    # TODO: Delete old archives if count > max_files (Task 2.3)
    _ = max_files

def setup_logging(config: AppConfig) -> None:
    """Initialize structlog with stdlib integration and configure output handlers.

    - Console output (ConsoleRenderer) is always enabled via StreamHandler(stderr).
    - When config.log_json_enabled is True, a FileHandler with JSONRenderer is added.
    - config.log_level controls the root logger level.
    - uvicorn.error and uvicorn.access logger handlers are overridden with
      structlog ProcessorFormatter.
    """
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

    # --- JSON file handler (optional) ---
    json_handler: logging.FileHandler | None = None
    if config.log_json_enabled:
        json_formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
        try:
            log_path = Path(config.log_json_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            json_handler = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
            json_handler.setFormatter(json_formatter)
        except OSError as exc:
            warnings.warn(
                f"Failed to open JSON log file {config.log_json_path!r}: {exc}",
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
        json_enabled=config.log_json_enabled,
        json_path=config.log_json_path if config.log_json_enabled else None,
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
