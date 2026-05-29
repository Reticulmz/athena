"""Unit tests for the taskiq worker logging configuration."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import structlog
from taskiq import TaskiqState

from osu_server.worker import startup

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Reset stdlib root logger and structlog config between tests."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level

    yield

    root.handlers = original_handlers
    root.level = original_level
    structlog.reset_defaults()


@pytest.mark.asyncio
async def test_worker_startup_configures_logging(tmp_path: Path) -> None:
    """ワーカー起動時に setup_logging が実行され、カスタムプロセッサ (マスク処理) が有効になる."""
    state = TaskiqState()

    # DB接続処理などをモック化して、logging の動作確認に専念する
    with (
        patch("osu_server.worker.create_engine"),
        patch("osu_server.worker.create_session_factory"),
        patch("osu_server.worker._config") as mock_config,
    ):
        mock_config.log_dir = str(tmp_path)
        mock_config.log_max_files = 30
        mock_config.log_level = "INFO"

        _ = await startup(state)  # pyright: ignore[reportGeneralTypeIssues,reportUnknownVariableType]

    logger: structlog.stdlib.BoundLogger = structlog.get_logger()  # pyright: ignore[reportAny]
    logger.info("worker_test_event", password="my_secret_password")

    # latest.jsonl からログを読み込んで検証する
    json_path = tmp_path / "latest.jsonl"
    content = json_path.read_text().strip()
    assert content != ""
    parsed: dict[str, object] = json.loads(content.split("\n")[-1])  # pyright: ignore[reportAny]
    assert parsed["event"] == "worker_test_event"
    # mask_sensitive_fields が適用されていることの確認
    assert parsed["password"] == "***"
