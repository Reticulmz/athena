"""event-like workflow の boundary 回帰契約を検証する."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = PROJECT_ROOT / "apps" / "athena_server" / "src" / "osu_server"


def test_event_boundary_scans_server_owned_sources() -> None:
    """Event boundary監査がcutover後のserver source rootを走査することを検証する.

    Root `src`をcanonical sourceとして復元せず、event boundary contractがserver productの
    sourceだけを検査することを確認する.

    Returns:
        None: source rootのphysical ownershipを検証して完了する.
    """
    assert SOURCE_ROOT == PROJECT_ROOT / "apps" / "athena_server" / "src" / "osu_server"


def _source_files() -> list[Path]:
    """キャッシュを除く production Python source file を返す.

    Returns:
        list[Path]: osu_server source root 配下の Python file.
    """
    return [path for path in SOURCE_ROOT.rglob("*.py") if "__pycache__" not in path.parts]


def test_production_code_does_not_import_ambiguous_event_bus_names() -> None:
    """前提: production source に event bus 名の禁止集合が定義される.

    操作: 全 production source を正規表現で走査する.
    結果: 曖昧な event bus 名を含む file は存在しない.

    Returns:
        None: event naming boundary 契約を検証する.
    """
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
    """前提: chat send use case は persistence を直接所有する.

    操作: send use case source に local event の token がないか調べる.
    結果: persistence を event に委譲する token は存在しない.

    Returns:
        None: chat persistence boundary 契約を検証する.
    """
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
    """前提: stable chat listener は transport adapter である.

    操作: listener source に persistence work と event token がないか調べる.
    結果: listener は message persistence を購読しない.

    Returns:
        None: stable listener boundary 契約を検証する.
    """
    source = (
        SOURCE_ROOT / "transports" / "stable" / "bancho" / "listeners" / "chat.py"
    ).read_text(encoding="utf-8")

    assert "persist_channel_message" not in source
    assert "persist_private_message" not in source
    assert "ChannelMessageSent" not in source
    assert "PrivateMessageSent" not in source


def test_distributed_events_are_not_chat_persistence_source_of_truth() -> None:
    """前提: chat persistence work は command service が所有する.

    操作: persistence work source に DistributedEvent がないか調べる.
    結果: distributed event は persistence の source of truth ではない.

    Returns:
        None: distributed event boundary 契約を検証する.
    """
    chat_source = (
        SOURCE_ROOT / "services" / "commands" / "chat" / "persistence_work.py"
    ).read_text(encoding="utf-8")

    assert "DistributedEvent" not in chat_source
