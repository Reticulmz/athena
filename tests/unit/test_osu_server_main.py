from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import uvicorn

import osu_server.__main__ as server_main

if TYPE_CHECKING:
    import pytest


@dataclass(frozen=True, slots=True)
class FakeConfig:
    server_host: str
    server_port: int
    environment: str


def test_main_launches_uvicorn_from_app_config(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_load_config() -> FakeConfig:
        return FakeConfig(
            server_host="0.0.0.0",
            server_port=8765,
            environment="development",
        )

    def fake_run(app: object, **kwargs: object) -> None:
        calls.append((app, dict(kwargs)))

    monkeypatch.setattr(server_main, "load_config", fake_load_config)
    monkeypatch.setattr(uvicorn, "run", fake_run)

    server_main.main()

    assert calls == [
        (
            "osu_server.app:app",
            {
                "host": "0.0.0.0",
                "port": 8765,
                "reload": True,
                "reload_dirs": ["src"],
                "access_log": False,
            },
        )
    ]


def test_main_disables_reload_outside_development(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_load_config() -> FakeConfig:
        return FakeConfig(
            server_host="127.0.0.1",
            server_port=9000,
            environment="test",
        )

    def fake_run(app: object, **kwargs: object) -> None:
        calls.append((app, dict(kwargs)))

    monkeypatch.setattr(server_main, "load_config", fake_load_config)
    monkeypatch.setattr(uvicorn, "run", fake_run)

    server_main.main()

    assert calls[0][1]["reload"] is False
    assert calls[0][1]["reload_dirs"] is None
