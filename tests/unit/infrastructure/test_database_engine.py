"""Database engine factory unit tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import pytest
    from sqlalchemy.ext.asyncio import AsyncEngine

from osu_server.infrastructure.database import engine as engine_module


class _CreateAsyncEngineRecorder:
    """create_async_engine() の呼び出し内容を記録するテストダブル。"""

    def __init__(self) -> None:
        self.url: str | None = None
        self.kwargs: dict[str, object] | None = None
        self.engine: AsyncEngine = cast("AsyncEngine", object())

    def __call__(self, url: str, **kwargs: object) -> AsyncEngine:
        self.url = url
        self.kwargs = kwargs
        return self.engine


def test_create_engine_enables_pool_pre_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    """stale connection を checkout 前に検出する pool_pre_ping を有効化する。"""
    recorder = _CreateAsyncEngineRecorder()
    installed_engines: list[AsyncEngine] = []
    monkeypatch.setattr(engine_module, "create_async_engine", recorder)
    monkeypatch.setattr(engine_module, "install_query_diagnostics", installed_engines.append)

    result = engine_module.create_engine("postgresql://user:pass@localhost/osu")

    assert result is recorder.engine
    assert recorder.url == "postgresql+asyncpg://user:pass@localhost/osu"
    assert recorder.kwargs == {"pool_pre_ping": True}
    assert installed_engines == [recorder.engine]
