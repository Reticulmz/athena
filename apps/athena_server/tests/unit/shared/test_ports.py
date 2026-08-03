"""Shared portのNoop実装が公開する型契約を検証するunit testを提供する."""

from __future__ import annotations

from typing import assert_type

from osu_server.shared.ports import (
    BeatmapLeaderboardRebuildWorkerWake,
    NoopBeatmapLeaderboardRebuildWorkerWake,
)


def test_leaderboard_rebuild_wake_port_exports_noop_implementation() -> None:
    """Noop worker wakeがleaderboard再構築portとして代入可能であることを検証する.

    Returns:
        None: Noop実装の具体型とport型の両方が同一instanceを参照することを確認する.
    """
    wake = NoopBeatmapLeaderboardRebuildWorkerWake()
    port: BeatmapLeaderboardRebuildWorkerWake = wake

    _ = assert_type(wake, NoopBeatmapLeaderboardRebuildWorkerWake)
    assert port is wake
