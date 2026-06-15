"""Boundary regression tests for event-like workflow classification."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = PROJECT_ROOT / "src" / "osu_server"


def _source_files() -> list[Path]:
    return [path for path in SOURCE_ROOT.rglob("*.py") if "__pycache__" not in path.parts]


def test_production_code_does_not_import_ambiguous_event_bus_names() -> None:
    forbidden = (
        re.compile(r"\bEventBus\b"),
        re.compile(r"\bInMemoryEventBus\b"),
        re.compile(r"infrastructure\.messaging\.interfaces"),
    )

    offenders = [
        path
        for path in _source_files()
        if any(pattern.search(path.read_text(encoding="utf-8")) for pattern in forbidden)
    ]

    assert offenders == []


def test_chat_send_use_cases_do_not_depend_on_local_events_for_persistence() -> None:
    send_modules = [
        SOURCE_ROOT / "services" / "commands" / "chat" / "send_channel_message.py",
        SOURCE_ROOT / "services" / "commands" / "chat" / "send_private_message.py",
    ]
    forbidden = ("LocalEventBus", "UserDisconnected", "ChannelMessageSent", "PrivateMessageSent")

    offenders = [
        path
        for path in send_modules
        if any(token in path.read_text(encoding="utf-8") for token in forbidden)
    ]

    assert offenders == []


def test_stable_chat_listener_does_not_subscribe_to_persistence_work() -> None:
    source = (
        SOURCE_ROOT / "transports" / "stable" / "bancho" / "listeners" / "chat.py"
    ).read_text(encoding="utf-8")

    assert "persist_channel_message" not in source
    assert "persist_private_message" not in source
    assert "ChannelMessageSent" not in source
    assert "PrivateMessageSent" not in source


def test_distributed_events_are_not_chat_persistence_source_of_truth() -> None:
    chat_source = (
        SOURCE_ROOT / "services" / "commands" / "chat" / "persistence_work.py"
    ).read_text(encoding="utf-8")

    assert "DistributedEvent" not in chat_source
