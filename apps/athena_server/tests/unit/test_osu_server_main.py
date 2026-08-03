"""__main__ entry pointがapp configをuvicorn設定へ写す契約を検証する."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn

import osu_server.__main__ as server_main

if TYPE_CHECKING:
    import pytest


@dataclass(frozen=True, slots=True)
class FakeConfig:
    """main entry pointに必要なserver設定だけを持つconfig fakeを表す.

    Attributes:
        server_host (str): uvicornへ渡すbind host.
        server_port (int): uvicornへ渡すbind port.
        environment (str): reload可否を決める実行environment.
    """

    server_host: str
    server_port: int
    environment: str


def test_main_launches_uvicorn_from_app_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Development configがuvicorn引数へ完全に写る契約を検証する.

    development環境のconfig loaderとuvicorn.runをfake化してmainを実行する.
    app pathとhostとportとreload設定が期待値で呼ばれることを確認する.

    Args:
        monkeypatch (pytest.MonkeyPatch): module dependencyをtest fakeへ差し替えるfixture.

    Returns:
        None: uvicorn呼び出し記録を検証して完了し,呼び出し側へ値を返さない.
    """
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_load_config() -> FakeConfig:
        """development用の固定server configを返す.

        Returns:
            FakeConfig: reloadを有効にするhostとportを持つconfig fake.
        """
        return FakeConfig(
            server_host="0.0.0.0",
            server_port=8765,
            environment="development",
        )

    def fake_run(app: object, **kwargs: object) -> None:
        """uvicorn.runの引数をassert用listへ記録する.

        Args:
            app (object): 起動対象としてuvicornへ渡されるapplication reference.
            **kwargs (object): app以外のuvicorn設定値.

        Returns:
            None: 呼び出し記録を追加して完了し,呼び出し側へ値を返さない.
        """
        calls.append((app, dict(kwargs)))

    monkeypatch.setattr(server_main, "load_config", fake_load_config)
    monkeypatch.setattr(uvicorn, "run", fake_run)

    server_main.main()

    source_root = Path(server_main.__file__).resolve().parents[1]

    assert calls == [
        (
            "osu_server.app:app",
            {
                "host": "0.0.0.0",
                "port": 8765,
                "reload": True,
                "reload_dirs": [str(source_root)],
                "access_log": False,
            },
        )
    ]


def test_main_disables_reload_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    """development以外のconfigがreloadを無効化する契約を検証する.

    test環境のconfig loaderとuvicorn.runをfake化してmainを実行する.
    reloadがFalseかつreload_dirsがNoneになることを確認する.

    Args:
        monkeypatch (pytest.MonkeyPatch): module dependencyをtest fakeへ差し替えるfixture.

    Returns:
        None: production相当のreload設定を検証して完了し,呼び出し側へ値を返さない.
    """
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_load_config() -> FakeConfig:
        """reloadを禁止するtest environmentのserver configを返す.

        Returns:
            FakeConfig: test環境のhostとportを持つconfig fake.
        """
        return FakeConfig(
            server_host="127.0.0.1",
            server_port=9000,
            environment="test",
        )

    def fake_run(app: object, **kwargs: object) -> None:
        """uvicorn.runの引数をassert用listへ記録する.

        Args:
            app (object): 起動対象としてuvicornへ渡されるapplication reference.
            **kwargs (object): app以外のuvicorn設定値.

        Returns:
            None: 呼び出し記録を追加して完了し,呼び出し側へ値を返さない.
        """
        calls.append((app, dict(kwargs)))

    monkeypatch.setattr(server_main, "load_config", fake_load_config)
    monkeypatch.setattr(uvicorn, "run", fake_run)

    server_main.main()

    assert calls[0][1]["reload"] is False
    assert calls[0][1]["reload_dirs"] is None
