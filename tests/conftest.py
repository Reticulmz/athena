"""Global test fixtures for structlog state management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Reset structlog configuration before each test.

    Ensures capture_logs() works correctly regardless of test ordering,
    by preventing logger caching across tests.
    """
    structlog.configure(cache_logger_on_first_use=False)

    yield

    structlog.configure(cache_logger_on_first_use=False)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)
