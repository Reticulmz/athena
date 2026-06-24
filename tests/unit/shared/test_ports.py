from __future__ import annotations

from typing import assert_type

from osu_server.shared.ports import (
    BeatmapLeaderboardRebuildWorkerWake,
    NoopBeatmapLeaderboardRebuildWorkerWake,
)


def test_leaderboard_rebuild_wake_port_exports_noop_implementation() -> None:
    wake = NoopBeatmapLeaderboardRebuildWorkerWake()
    port: BeatmapLeaderboardRebuildWorkerWake = wake

    _ = assert_type(wake, NoopBeatmapLeaderboardRebuildWorkerWake)
    assert port is wake
