"""structlogとstdlibを統合するstructured logging初期化を提供するmodule.

consoleとJSON fileへ同じprocessor chainで出力し, uvicornを含むstdlib loggerを
structlogのProcessorFormatter経由へ統一する.
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
    """process間のlogging sessionを表すfile lockの保持状態.

    Attributes:
        file (TextIO | None): 開いたlock file. 未取得時はNone.
        path (Path | None): ``file``に対応するlock file path. 未取得時はNone.

    Notes:
        ``fcntl``が利用できるplatformだけがこの状態でprocess間sessionを共有する.
        ``fcntl``がないfallbackではfileとpathを保持せず, process間のsession判定を行わない.
    """

    file: TextIO | None = None
    path: Path | None = None


_SESSION_LOCK = _LoggingSessionLock()


def mask_sensitive_fields(
    _logger: structlog.types.WrappedLogger,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """Credential leakageを防ぐためsensitive fieldの値を``"***"``へ置換する.

    Args:
        _logger (structlog.types.WrappedLogger): structlog processorが渡すlogger. 使用しない.
        _method_name (str): logger method名. 使用しない.
        event_dict (structlog.types.EventDict): 出力直前のstructured logging event.

    Returns:
        structlog.types.EventDict: sensitive keyをmaskした同一event mapping.

    Notes:
        mappingはin-placeで更新し, ``password``, ``password_hash``, ``password_md5``だけをmaskする.
    """
    for key in _SENSITIVE_KEYS:
        if key in event_dict:
            event_dict[key] = "***"
    return event_dict


def _archive_latest_file(latest_path: Path, log_dir: Path) -> None:
    """``latest.jsonl``を日付連番のgzip fileへarchiveして元fileを削除する.

    Args:
        latest_path (Path): archiveする``latest.jsonl``のpath.
        log_dir (Path): gzip archiveを作成するdirectory.

    Returns:
        None: archive作成後にsource fileを削除し値を返さない.

    Raises:
        OSError: sourceまたはarchive fileのread/write/deleteに失敗した場合.
    """
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
            except ValueError, IndexError:
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
    """archive数が上限を超えたとき更新時刻が古いfileを削除する.

    Args:
        log_dir (Path): ``*.jsonl.gz`` archiveを検索するdirectory.
        max_files (int): 保持するarchive fileの最大数.

    Returns:
        None: 不要なarchiveを削除して値を返さない.

    Notes:
        statまたは削除のOSErrorはwarningに記録し, 残りのfileの処理を続ける.
    """
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
    """Logging sessionのlock fileを開く.

    Args:
        log_dir (Path): lock fileを作るdirectory.
        lock_path (Path): append modeで開くlock file path.

    Returns:
        TextIO | None: 開いたlock file. directory作成またはopen失敗時はNone.

    Notes:
        OSErrorはwarningに記録してcallerが安全にrotationをskipできるようにする.
    """
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
    """既に開始済みのlogging session用にshared lockを取得する.

    Args:
        lock_file (TextIO): shared lockを取得する開済みfile.
        lock_path (Path): warning messageに使うlock file path.

    Returns:
        bool: shared lockを取得できた場合はTrue. 非対応platformまたはOSError時はFalse.

    Notes:
        ``fcntl``がないplatformではfile lockを扱えないためFalseを返す.
    """
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
    """このlog directoryを使う最初のactive processだけを判定する.

    Args:
        log_dir (Path): process間でsessionを共有するlogging directory.

    Returns:
        bool: current processが``latest.jsonl``をrotateすべき場合はTrue.

    Notes:
        ``fcntl``がないfallbackではsession lockを作らないため, 各processがTrueを受け取る.
        その場合はprocess間の排他制御なしでarchiveを試行する.
    """
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
    """後続processがactive sessionを検出できるようlockをshared lockへ降格する.

    Returns:
        None: lock状態を更新するだけで値を返さない.

    Notes:
        lockを保持していない場合, または``fcntl``非対応platformでは何もしない.
    """
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
    """起動時の``latest.jsonl``をarchiveし, 古いarchiveを削除する.

    Args:
        log_dir (Path): ``latest.jsonl``とarchiveを格納するdirectory.
        max_files (int): 保持するgzip archiveの最大数.

    Returns:
        None: rotationを実行またはskipして値を返さない.

    Notes:
        非空の``latest.jsonl``だけを対象にする.
        ``fcntl``が利用可能な場合はprocess間lockを取得できた場合だけrotationする.
        ``fcntl``がないfallbackではprocess lockなしでarchiveを試行するため, 同時process間の
        排他制御は保証しない.
        すべてのOSErrorは``warnings.warn``へ記録し, application起動を継続する.
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
    """structlogとstdlib loggerを初期化してconsole/JSON handlerを設定する.

    Args:
        config (AppConfig): log directory, 最大archive数, root log levelを持つapplication設定.

    Returns:
        None: process全体のlogging handlerを設定するだけで値を返さない.

    Notes:
        ``fcntl``が利用可能な場合はactive logging sessionごとに一度だけrotationを試行する.
        ``fcntl``がないfallbackでは各processがrotationを試行し, process間の排他制御は行わない.
        console outputは常にstderrへ出力する.
        JSON handlerの作成に成功した場合だけ``latest.jsonl``へ追加出力する.
        JSON handlerの作成がOSErrorで失敗した場合はwarningを記録し, console outputだけを継続する.
        ``uvicorn.error``と``uvicorn.access``のhandlerもstructlog formatterへ置き換える.
    """
    # 起動時ローテーションの実行
    log_dir_path = Path(config.log_dir)
    if _prepare_process_logging_session(log_dir_path):
        try:
            rotate_logs(log_dir_path, config.log_max_files)
        finally:
            _downgrade_process_logging_session()

    shared_processors: list[structlog.types.Processor] = [  # pyright: ignore[reportAssignmentType]
        structlog.contextvars.merge_contextvars,
        mask_sensitive_fields,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
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
    for handler in root_logger.handlers:
        if hasattr(handler, "close"):
            handler.close()
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
    """Uvicorn loggerのhandlerをstructlog formatterへ到達するhandlerに置換する.

    Args:
        console_handler (logging.Handler): 常時利用するconsole output handler.
        json_handler (logging.Handler | None): 利用可能な場合に追加するJSON file handler.

    Returns:
        None: 対象loggerのhandlerを置換するだけで値を返さない.
    """
    for logger_name in ("uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        for handler in uvicorn_logger.handlers:
            if hasattr(handler, "close"):
                handler.close()
        uvicorn_logger.handlers.clear()
        uvicorn_logger.addHandler(console_handler)
        if json_handler is not None:
            uvicorn_logger.addHandler(json_handler)
        uvicorn_logger.propagate = False
