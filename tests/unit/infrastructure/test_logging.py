"""Tests for infrastructure/logging.py — structlog initialization and sensitive field masking."""

from __future__ import annotations

import json
import logging
import sys
import typing
from typing import TYPE_CHECKING

import pytest
import structlog
from structlog.testing import capture_logs

from osu_server.infrastructure.logging import mask_sensitive_fields, setup_logging
from tests.factories.config import make_app_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Reset stdlib root logger and structlog config between tests."""
    root = logging.getLogger()
    # Save original state
    original_handlers = root.handlers[:]
    original_level = root.level

    yield

    # Restore
    root.handlers = original_handlers
    root.level = original_level
    structlog.reset_defaults()


# --- mask_sensitive_fields tests ---


class TestMaskSensitiveFields:
    """Tests for the mask_sensitive_fields processor."""

    def test_masks_password_key(self) -> None:
        """password key is replaced with '***'."""
        event_dict: structlog.types.EventDict = {"event": "login", "password": "secret123"}
        result = mask_sensitive_fields(None, "info", event_dict)  # type: ignore[arg-type]  # processor test: logger arg unused, pass None
        assert result["password"] == "***"

    def test_masks_password_hash_key(self) -> None:
        """password_hash key is replaced with '***'."""
        event_dict: structlog.types.EventDict = {
            "event": "login",
            "password_hash": "abc123hash",
        }
        result = mask_sensitive_fields(None, "info", event_dict)  # type: ignore[arg-type]  # processor test: logger arg unused, pass None
        assert result["password_hash"] == "***"

    def test_masks_password_md5_key(self) -> None:
        """password_md5 key is replaced with '***'."""
        event_dict: structlog.types.EventDict = {
            "event": "login",
            "password_md5": "d41d8cd98f",
        }
        result = mask_sensitive_fields(None, "info", event_dict)  # type: ignore[arg-type]  # processor test: logger arg unused, pass None
        assert result["password_md5"] == "***"

    def test_masks_multiple_sensitive_keys(self) -> None:
        """All sensitive keys are masked in a single event_dict."""
        event_dict: structlog.types.EventDict = {
            "event": "login",
            "password": "pw",
            "password_hash": "hash",
            "password_md5": "md5",
        }
        result = mask_sensitive_fields(None, "info", event_dict)  # type: ignore[arg-type]  # processor test: logger arg unused, pass None
        assert result["password"] == "***"
        assert result["password_hash"] == "***"
        assert result["password_md5"] == "***"

    def test_preserves_non_sensitive_keys(self) -> None:
        """Non-sensitive keys are not modified."""
        event_dict: structlog.types.EventDict = {
            "event": "login",
            "username": "player1",
            "ip": "127.0.0.1",
        }
        result = mask_sensitive_fields(None, "info", event_dict)  # type: ignore[arg-type]  # processor test: logger arg unused, pass None
        assert result["username"] == "player1"
        assert result["ip"] == "127.0.0.1"

    def test_returns_event_dict(self) -> None:
        """Processor returns the event_dict (structlog protocol)."""
        event_dict: structlog.types.EventDict = {"event": "test"}
        result = mask_sensitive_fields(None, "info", event_dict)  # type: ignore[arg-type]  # processor test: logger arg unused, pass None
        assert result is event_dict


# --- setup_logging tests ---


class TestSetupLogging:
    """Tests for setup_logging configuration."""

    def test_configures_root_logger_level(self) -> None:
        """Root logger level is set from config.log_level."""
        config = make_app_config(log_level="DEBUG")
        setup_logging(config)
        assert logging.getLogger().level == logging.DEBUG

    def test_configures_root_logger_level_warning(self) -> None:
        """Root logger level correctly handles WARNING."""
        config = make_app_config(log_level="WARNING")
        setup_logging(config)
        assert logging.getLogger().level == logging.WARNING

    def test_adds_console_handler(self) -> None:
        """A StreamHandler for console output is always added."""
        config = make_app_config()
        setup_logging(config)
        root = logging.getLogger()
        stream_handlers: list[logging.StreamHandler[typing.Any]] = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler) and h.stream is sys.stderr  # pyright: ignore[reportUnknownMemberType]
        ]
        assert len(stream_handlers) >= 1

    def test_adds_file_handler_always(self, tmp_path: Path) -> None:
        """FileHandler is always added to log_dir/latest.jsonl."""
        config = make_app_config(log_dir=str(tmp_path))
        setup_logging(config)
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1

    def test_json_file_handler_writes_json(self, tmp_path: Path) -> None:
        """JSON file handler writes valid JSON lines to latest.jsonl."""
        config = make_app_config(log_dir=str(tmp_path))
        setup_logging(config)

        logger: typing.Any = structlog.get_logger()  # pyright: ignore[reportAny]
        logger.info("test_event", key="value")  # pyright: ignore[reportAny]

        json_path = tmp_path / "latest.jsonl"
        content = json_path.read_text()
        assert content.strip() != ""
        parsed: dict[str, typing.Any] = json.loads(content.strip().split("\n")[-1])  # pyright: ignore[reportAny]
        assert parsed["event"] == "test_event"
        assert parsed["key"] == "value"

    def test_json_write_failure_does_not_crash(self) -> None:
        """If JSON file path is not writable, setup_logging warns but continues."""
        config = make_app_config(
            log_dir="/nonexistent/impossible/path",
        )
        # Should emit a warning and not raise
        with pytest.warns(UserWarning, match="Failed to open JSON log file"):
            setup_logging(config)

        # structlog should still work via console
        logger: typing.Any = structlog.get_logger()  # pyright: ignore[reportAny]
        logger.info("still_works")  # pyright: ignore[reportAny]

    def test_structlog_get_logger_works_after_setup(self) -> None:
        """structlog.get_logger() returns a usable logger after setup."""
        config = make_app_config()
        setup_logging(config)
        logger: typing.Any = structlog.get_logger()  # pyright: ignore[reportAny]
        assert logger is not None

        # Should be able to log without error
        with capture_logs() as cap_logs:
            logger.info("hello", user="test")  # pyright: ignore[reportAny]

        assert len(cap_logs) == 1
        assert cap_logs[0]["event"] == "hello"
        assert cap_logs[0]["user"] == "test"

    def test_overrides_uvicorn_error_logger_handlers(self) -> None:
        """uvicorn.error logger handlers are overridden with structlog formatter."""
        config = make_app_config()
        setup_logging(config)
        uvicorn_error = logging.getLogger("uvicorn.error")
        assert len(uvicorn_error.handlers) >= 1
        for handler in uvicorn_error.handlers:
            formatter = handler.formatter
            assert formatter is not None
            assert "ProcessorFormatter" in type(formatter).__name__

    def test_overrides_uvicorn_access_logger_handlers(self) -> None:
        """uvicorn.access logger handlers are overridden with structlog formatter."""
        config = make_app_config()
        setup_logging(config)
        uvicorn_access = logging.getLogger("uvicorn.access")
        assert len(uvicorn_access.handlers) >= 1
        for handler in uvicorn_access.handlers:
            formatter = handler.formatter
            assert formatter is not None
            assert "ProcessorFormatter" in type(formatter).__name__

    def test_mask_sensitive_fields_in_processor_chain(self, tmp_path: Path) -> None:
        """Sensitive fields are masked when logging through the full JSON output chain."""
        config = make_app_config(log_dir=str(tmp_path))
        setup_logging(config)

        logger: typing.Any = structlog.get_logger()  # pyright: ignore[reportAny]
        logger.info("login_attempt", password="secret", username="player1")  # pyright: ignore[reportAny]

        json_path = tmp_path / "latest.jsonl"
        content = json_path.read_text().strip()
        assert content != ""
        parsed: dict[str, typing.Any] = json.loads(content.split("\n")[-1])  # pyright: ignore[reportAny]
        assert parsed["event"] == "login_attempt"
        assert parsed["password"] == "***"
        assert parsed["username"] == "player1"
