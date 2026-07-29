"""database engine factoryのconnection pool設定契約を検証するmodule."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import pytest
    from sqlalchemy.ext.asyncio import AsyncEngine

from osu_server.infrastructure.database import engine as engine_module


class _CreateAsyncEngineRecorder:
    """create_async_engine呼び出しを記録して固定engineを返すtest double.

    Attributes:
        url (str | None): 受信したdatabase URL.
        kwargs (dict[str, object] | None): 受信したengine作成keyword args.
        engine (AsyncEngine): fakeが返す固定async engine.
    """

    def __init__(self) -> None:
        """call履歴と返却用async engineを初期化する."""
        self.url: str | None = None
        self.kwargs: dict[str, object] | None = None
        self.engine: AsyncEngine = cast("AsyncEngine", object())

    def __call__(self, url: str, **kwargs: object) -> AsyncEngine:
        """URLとkeyword argsを記録して固定async engineを返す.

        Args:
            url (str): create_async_engineへ渡されたdatabase URL.
            **kwargs (object): create_async_engineへ渡されたkeyword args.

        Returns:
            AsyncEngine: testが比較する固定async engine.
        """
        self.url = url
        self.kwargs = kwargs
        return self.engine


def test_create_engine_enables_pool_pre_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    """engine作成時にpool_pre_pingとquery diagnosticsを有効化することを検証する.

    Args:
        monkeypatch (pytest.MonkeyPatch): engine factoryとdiagnostics installerを
            recording fakeへ置換するfixture.

    Returns:
        None: engine作成argsとinstaller呼び出しを検証して値を返さず完了する.
    """
    recorder = _CreateAsyncEngineRecorder()
    installed_engines: list[AsyncEngine] = []
    monkeypatch.setattr(engine_module, "create_async_engine", recorder)
    monkeypatch.setattr(engine_module, "install_query_diagnostics", installed_engines.append)

    result = engine_module.create_engine("postgresql://user:pass@localhost/osu")

    assert result is recorder.engine
    assert recorder.url == "postgresql+asyncpg://user:pass@localhost/osu"
    assert recorder.kwargs == {"pool_pre_ping": True}
    assert installed_engines == [recorder.engine]
