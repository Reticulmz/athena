"""Stable compatibility enum value tests."""

from osu_server.domain.compatibility.stable import (
    StableMode,
    StablePresenceFilter,
    StableStatus,
)


def test_stable_status_values_match_guide() -> None:
    members = [(member.name, member.value) for member in StableStatus]

    assert members == [
        ("Idle", 0),
        ("Afk", 1),
        ("Playing", 2),
        ("Editing", 3),
        ("Modding", 4),
        ("Multiplayer", 5),
        ("Watching", 6),
        ("Unknown", 7),
        ("Testing", 8),
        ("Submitting", 9),
        ("Paused", 10),
        ("Lobby", 11),
        ("Multiplaying", 12),
        ("OsuDirect", 13),
    ]


def test_stable_mode_values_match_guide() -> None:
    members = [(member.name, member.value) for member in StableMode]

    assert members == [
        ("Osu", 0),
        ("Taiko", 1),
        ("Fruits", 2),
        ("Mania", 3),
    ]


def test_stable_presence_filter_values_match_guide() -> None:
    members = [(member.name, member.value) for member in StablePresenceFilter]

    assert members == [
        ("NoPlayers", 0),
        ("All", 1),
        ("Friends", 2),
    ]
