"""infrastructure loggingの初期化と機密field masking契約を検証するmodule."""

from __future__ import annotations

import json
import logging
import warnings
from typing import TYPE_CHECKING, Protocol, cast

import pytest
import structlog
from structlog.testing import capture_logs

from osu_server.infrastructure.logging import mask_sensitive_fields, setup_logging
from tests.factories.config import make_app_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def reset_logging() -> Iterator[None]:
    """各testの前後でstdlib root loggerとstructlog設定を復元する.

    Yields:
        None: testを実行可能なreset済みlogging環境を提供する.
    """
    root = logging.getLogger()
    # Save original state
    original_handlers = root.handlers[:]
    original_level = root.level

    yield

    # Close handlers added by setup_logging (including uvicorn handlers)
    for handler in root.handlers:
        if hasattr(handler, "close"):
            handler.close()
    for logger_name in ("uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(logger_name).handlers:
            if hasattr(handler, "close"):
                handler.close()
    # Restore
    root.handlers = original_handlers
    root.level = original_level
    structlog.reset_defaults()


# --- mask_sensitive_fields tests ---


class StructlogInfoLogger(Protocol):
    """testが使用するstructlog info loggerの最小contractを表す.

    `info`はevent名と任意fieldを受け取り, 記録backend固有のresultを返す.
    """

    def info(self, event: str, **kwargs: object) -> object:
        """Eventとstructured fieldを記録する.

        Args:
            event (str): 記録するevent名.
            **kwargs (object): eventへ付加するstructured field.

        Returns:
            object: structlog backendが返すresult.
        """
        ...


def _mask_event_fields(event_dict: dict[str, object]) -> dict[str, object]:
    """Mask processorへevent dictionaryを渡しresultをtyped値として返す.

    Args:
        event_dict (dict[str, object]): masking対象のstructured event field.

    Returns:
        dict[str, object]: processorが返した同一または更新済みevent dictionary.
    """
    logger = cast("structlog.types.WrappedLogger", object())
    masked = mask_sensitive_fields(logger, "info", event_dict)
    return cast("dict[str, object]", masked)


def _get_test_logger() -> StructlogInfoLogger:
    """現在のstructlog設定に従うtest用info loggerを取得する.

    Returns:
        StructlogInfoLogger: event記録に使うtyped logger.
    """
    return cast("StructlogInfoLogger", structlog.get_logger())


def _decode_last_json_line(content: str) -> dict[str, object]:
    """JSON Lines出力の最終行をobject dictionaryとして復号する.

    Args:
        content (str): 1行以上のJSON Lines形式logging出力.

    Returns:
        dict[str, object]: 最終行から復号したstructured event.
    """
    decoded = cast("object", json.loads(content.strip().split("\n")[-1]))
    assert isinstance(decoded, dict)
    return cast("dict[str, object]", decoded)


class TestMaskSensitiveFields:
    """mask_sensitive_fields processorの機密field置換契約を検証するtest群."""

    def test_masks_password_key(self) -> None:
        """Password fieldを含むeventで値がmaskへ置換されることを検証する.

        Returns:
            None: password fieldのobservable masking結果を検証して完了する.
        """
        event_dict: dict[str, object] = {"event": "login", "password": "secret123"}
        result = _mask_event_fields(event_dict)
        assert result["password"] == "***"

    def test_masks_password_hash_key(self) -> None:
        """password_hash fieldを含むeventで値がmaskへ置換されることを検証する.

        Returns:
            None: password_hash fieldのobservable masking結果を検証して完了する.
        """
        event_dict: dict[str, object] = {
            "event": "login",
            "password_hash": "abc123hash",
        }
        result = _mask_event_fields(event_dict)
        assert result["password_hash"] == "***"

    def test_masks_password_md5_key(self) -> None:
        """password_md5 fieldを含むeventで値がmaskへ置換されることを検証する.

        Returns:
            None: password_md5 fieldのobservable masking結果を検証して完了する.
        """
        event_dict: dict[str, object] = {
            "event": "login",
            "password_md5": "d41d8cd98f",
        }
        result = _mask_event_fields(event_dict)
        assert result["password_md5"] == "***"

    def test_masks_multiple_sensitive_keys(self) -> None:
        """複数の機密fieldを含むeventで全値がmaskされることを検証する.

        Returns:
            None: すべての対象fieldのobservable masking結果を検証して完了する.
        """
        event_dict: dict[str, object] = {
            "event": "login",
            "password": "pw",
            "password_hash": "hash",
            "password_md5": "md5",
        }
        result = _mask_event_fields(event_dict)
        assert result["password"] == "***"
        assert result["password_hash"] == "***"
        assert result["password_md5"] == "***"

    def test_preserves_non_sensitive_keys(self) -> None:
        """機密でないfieldを含むeventで元の値が維持されることを検証する.

        Returns:
            None: usernameとIP addressの非変更結果を検証して完了する.
        """
        event_dict: dict[str, object] = {
            "event": "login",
            "username": "player1",
            "ip": "127.0.0.1",
        }
        result = _mask_event_fields(event_dict)
        assert result["username"] == "player1"
        assert result["ip"] == "127.0.0.1"

    def test_returns_event_dict(self) -> None:
        """Processorがstructlog protocolどおりinput event dictionaryを返すことを検証する.

        Returns:
            None: inputとのidentityを検証して完了する.
        """
        event_dict: dict[str, object] = {"event": "test"}
        result = _mask_event_fields(event_dict)
        assert result is event_dict


# --- setup_logging tests ---


class TestSetupLogging:
    """setup_loggingが構成するloggerとhandlerの契約を検証するtest群."""

    def test_configures_root_logger_level(self) -> None:
        """DEBUG log levelを指定したconfigでroot loggerのlevelが設定されることを検証する.

        Returns:
            None: root loggerのDEBUG levelを検証して完了する.
        """
        config = make_app_config(log_level="DEBUG")
        setup_logging(config)
        assert logging.getLogger().level == logging.DEBUG

    def test_configures_root_logger_level_warning(self) -> None:
        """WARNING log levelを指定したconfigでroot loggerのlevelが設定されることを検証する.

        Returns:
            None: root loggerのWARNING levelを検証して完了する.
        """
        config = make_app_config(log_level="WARNING")
        setup_logging(config)
        assert logging.getLogger().level == logging.WARNING

    def test_adds_console_handler(self) -> None:
        """既定configでconsole出力用StreamHandlerが追加されることを検証する.

        Returns:
            None: non-file StreamHandlerの存在を検証して完了する.
        """
        config = make_app_config()
        setup_logging(config)
        root = logging.getLogger()
        stream_handler_count = sum(
            1
            for handler in root.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        )
        assert stream_handler_count >= 1

    def test_adds_file_handler_always(self, tmp_path: Path) -> None:
        """指定log directoryでlatest.jsonl用FileHandlerが追加されることを検証する.

        Args:
            tmp_path (Path): test固有の書き込み可能なlog directory.

        Returns:
            None: FileHandlerの個数を検証して完了する.
        """
        config = make_app_config(log_dir=str(tmp_path))
        setup_logging(config)
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1

    def test_json_file_handler_writes_json(self, tmp_path: Path) -> None:
        """JSON file handlerがlatest.jsonlへparse可能なeventを書き込むことを検証する.

        Args:
            tmp_path (Path): test固有の書き込み可能なlog directory.

        Returns:
            None: JSON Linesのevent fieldとvalueを検証して完了する.
        """
        config = make_app_config(log_dir=str(tmp_path))
        setup_logging(config)

        logger = _get_test_logger()
        _ = logger.info("test_event", key="value")

        json_path = tmp_path / "latest.jsonl"
        content = json_path.read_text()
        assert content.strip() != ""
        parsed = _decode_last_json_line(content)
        assert parsed["event"] == "test_event"
        assert parsed["key"] == "value"

    def test_second_setup_logging_does_not_rotate_active_session(self, tmp_path: Path) -> None:
        """同一process内の再設定でactive latest.jsonlをarchiveしないことを検証する.

        Args:
            tmp_path (Path): preexisting log fileを配置するtest directory.

        Returns:
            None: active content維持とarchive個数を検証して完了する.
        """
        config = make_app_config(log_dir=str(tmp_path))
        latest_path = tmp_path / "latest.jsonl"
        _ = latest_path.write_text('{"event": "previous_session"}\n')

        setup_logging(config)
        assert list(tmp_path.glob("*.jsonl.gz"))

        active_session_content = latest_path.read_text()
        setup_logging(config)

        assert latest_path.read_text().startswith(active_session_content)
        assert len(list(tmp_path.glob("*.jsonl.gz"))) == 1

    def test_json_write_failure_does_not_crash(self, tmp_path: Path) -> None:
        """書き込み不能なJSON log pathでwarningを出してloggingを継続することを検証する.

        Args:
            tmp_path (Path): fileをdirectoryとして誤用するtest path.

        Returns:
            None: UserWarningとconsole logging継続を検証して完了する.
        """
        blocked_log_dir = tmp_path / "not-a-directory"
        _ = blocked_log_dir.write_text("existing file")
        config = make_app_config(
            log_dir=str(blocked_log_dir),
        )
        with warnings.catch_warnings(record=True) as _w:
            warnings.simplefilter("always")
            setup_logging(config)

        assert any(w.category is UserWarning for w in _w)

        # structlog should still work via console
        logger = _get_test_logger()
        _ = logger.info("still_works")

    def test_structlog_get_logger_works_after_setup(self) -> None:
        """設定後のstructlog loggerがeventを記録できることを検証する.

        Returns:
            None: captureしたeventとuser fieldを検証して完了する.
        """
        config = make_app_config()
        setup_logging(config)
        logger = _get_test_logger()
        assert logger is not None

        # Should be able to log without error
        with capture_logs() as cap_logs:
            _ = logger.info("hello", user="test")

        assert len(cap_logs) == 1
        assert cap_logs[0]["event"] == "hello"
        assert cap_logs[0]["user"] == "test"

    def test_overrides_uvicorn_error_logger_handlers(self) -> None:
        """uvicorn.error handlerがstructlog formatterへ置換されることを検証する.

        Returns:
            None: handlerのProcessorFormatter設定を検証して完了する.
        """
        config = make_app_config()
        setup_logging(config)
        uvicorn_error = logging.getLogger("uvicorn.error")
        assert len(uvicorn_error.handlers) >= 1
        for handler in uvicorn_error.handlers:
            formatter = handler.formatter
            assert formatter is not None
            assert "ProcessorFormatter" in type(formatter).__name__

    def test_overrides_uvicorn_access_logger_handlers(self) -> None:
        """uvicorn.access handlerがstructlog formatterへ置換されることを検証する.

        Returns:
            None: handlerのProcessorFormatter設定を検証して完了する.
        """
        config = make_app_config()
        setup_logging(config)
        uvicorn_access = logging.getLogger("uvicorn.access")
        assert len(uvicorn_access.handlers) >= 1
        for handler in uvicorn_access.handlers:
            formatter = handler.formatter
            assert formatter is not None
            assert "ProcessorFormatter" in type(formatter).__name__

    def test_mask_sensitive_fields_in_processor_chain(self, tmp_path: Path) -> None:
        """完全なJSON processor chainでも機密fieldがmaskされることを検証する.

        Args:
            tmp_path (Path): JSON outputを保存するtest固有directory.

        Returns:
            None: serialized eventのmasked passwordと維持されたusernameを検証して完了する.
        """
        config = make_app_config(log_dir=str(tmp_path))
        setup_logging(config)

        logger = _get_test_logger()
        _ = logger.info("login_attempt", password="secret", username="player1")

        json_path = tmp_path / "latest.jsonl"
        content = json_path.read_text().strip()
        assert content != ""
        parsed = _decode_last_json_line(content)
        assert parsed["event"] == "login_attempt"
        assert parsed["password"] == "***"
        assert parsed["username"] == "player1"
