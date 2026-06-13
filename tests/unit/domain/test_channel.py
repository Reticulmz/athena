"""Tests for Channel domain model, ChannelType enum, and channel-related domain events.

Validates:
- Req 1.1: Channel dataclass with required fields
- Req 1.3: Channel name validation (# + [a-z0-9_-])
- Req 1.5: ChannelType enum with PUBLIC and reserved variants
- Req 6.1: ChannelMessageSent domain event
- Req 6.2: PrivateMessageSent domain event
"""

# ruff: noqa: A002
from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from enum import Enum

import pytest

from osu_server.domain.chat.channels import Channel, ChannelRoleOverride, ChannelType
from osu_server.domain.events import Event
from osu_server.domain.events.channels import ChannelMessageSent, PrivateMessageSent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
from tests.factories.domain import make_channel
from tests.support import assert_rejects_setattr

_NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _make_channel(
    *,
    id: int = 1,
    name: str = "#osu",
    topic: str = "General discussion",
    channel_type: ChannelType = ChannelType.PUBLIC,
    auto_join: bool = True,
    rate_limit_messages: int | None = None,
    rate_limit_window: int | None = None,
    created_at: datetime = _NOW,
    updated_at: datetime = _NOW,
) -> Channel:
    return make_channel(
        id=id,
        name=name,
        topic=topic,
        channel_type=channel_type,
        auto_join=auto_join,
        rate_limit_messages=rate_limit_messages,
        rate_limit_window=rate_limit_window,
        created_at=created_at,
        updated_at=updated_at,
    )


# ===========================================================================
# ChannelType enum
# ===========================================================================


class TestChannelType:
    """Req 1.5: ChannelType enum with PUBLIC and reserved variants."""

    def test_is_enum(self) -> None:
        assert issubclass(ChannelType, Enum)

    def test_public_value(self) -> None:
        assert ChannelType.PUBLIC.value == "public"

    def test_reserved_variants_exist(self) -> None:
        assert ChannelType.MULTIPLAYER.value == "multiplayer"
        assert ChannelType.SPECTATOR.value == "spectator"
        assert ChannelType.TEMPORARY.value == "temporary"

    def test_total_member_count(self) -> None:
        assert len(ChannelType) == 4


# ===========================================================================
# Channel dataclass
# ===========================================================================


class TestChannelDataclass:
    """Req 1.1: Channel dataclass with required fields."""

    def test_slots_enabled(self) -> None:
        assert hasattr(Channel, "__slots__")

    def test_creation(self) -> None:
        ch = _make_channel()
        assert ch.id == 1
        assert ch.name == "#osu"
        assert ch.topic == "General discussion"
        assert ch.channel_type == ChannelType.PUBLIC
        assert ch.auto_join is True
        assert ch.rate_limit_messages is None
        assert ch.rate_limit_window is None
        assert ch.created_at == _NOW
        assert ch.updated_at == _NOW

    def test_all_expected_fields(self) -> None:
        expected = {
            "id",
            "name",
            "topic",
            "channel_type",
            "auto_join",
            "rate_limit_messages",
            "rate_limit_window",
            "created_at",
            "updated_at",
        }
        actual = {f.name for f in fields(Channel)}
        assert actual == expected

    def test_rate_limit_nullable(self) -> None:
        ch = _make_channel(rate_limit_messages=5, rate_limit_window=30)
        assert ch.rate_limit_messages == 5
        assert ch.rate_limit_window == 30


# ===========================================================================
# Channel name validation
# ===========================================================================


class TestChannelNameValidation:
    """Req 1.3: Channel name must match # + [a-z0-9_-]."""

    def test_valid_names(self) -> None:
        for name in ("#osu", "#announce", "#lobby-1", "#multi_room", "#a123"):
            ch = _make_channel(name=name)
            assert ch.name == name

    def test_missing_hash_prefix(self) -> None:
        with pytest.raises(ValueError, match="must start with '#'"):
            _ = _make_channel(name="osu")

    def test_empty_after_hash(self) -> None:
        with pytest.raises(ValueError, match="at least one character after '#'"):
            _ = _make_channel(name="#")

    def test_uppercase_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid characters"):
            _ = _make_channel(name="#OSU")

    def test_space_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid characters"):
            _ = _make_channel(name="#osu chat")

    def test_special_chars_rejected(self) -> None:
        for name in ("#osu!", "#a@b", "#chan.el", "#ch/an"):
            with pytest.raises(ValueError, match="invalid characters"):
                _ = _make_channel(name=name)

    def test_hyphen_allowed(self) -> None:
        ch = _make_channel(name="#my-channel")
        assert ch.name == "#my-channel"

    def test_underscore_allowed(self) -> None:
        ch = _make_channel(name="#my_channel")
        assert ch.name == "#my_channel"

    def test_digits_allowed(self) -> None:
        ch = _make_channel(name="#room42")
        assert ch.name == "#room42"


# ===========================================================================
# ChannelMessageSent event
# ===========================================================================


class TestChannelMessageSent:
    """Req 6.1: ChannelMessageSent domain event."""

    def test_is_subclass_of_event(self) -> None:
        assert issubclass(ChannelMessageSent, Event)

    def test_instance_is_event(self) -> None:
        event = ChannelMessageSent(
            sender_id=1,
            sender_name="Player",
            channel_name="#osu",
            content="hello",
        )
        assert isinstance(event, Event)

    def test_frozen(self) -> None:
        event = ChannelMessageSent(
            sender_id=1,
            sender_name="Player",
            channel_name="#osu",
            content="hello",
        )
        assert_rejects_setattr(event, "sender_id", 2)

    def test_slots_enabled(self) -> None:
        assert hasattr(ChannelMessageSent, "__slots__")

    def test_fields(self) -> None:
        field_names = {f.name for f in fields(ChannelMessageSent)}
        assert field_names == {"sender_id", "sender_name", "channel_name", "content"}

    def test_field_values(self) -> None:
        event = ChannelMessageSent(
            sender_id=42,
            sender_name="TestPlayer",
            channel_name="#osu",
            content="hello world",
        )
        assert event.sender_id == 42
        assert event.sender_name == "TestPlayer"
        assert event.channel_name == "#osu"
        assert event.content == "hello world"

    def test_equality(self) -> None:
        a = ChannelMessageSent(sender_id=1, sender_name="P", channel_name="#osu", content="hi")
        b = ChannelMessageSent(sender_id=1, sender_name="P", channel_name="#osu", content="hi")
        assert a == b

    def test_inequality(self) -> None:
        a = ChannelMessageSent(sender_id=1, sender_name="P", channel_name="#osu", content="hi")
        b = ChannelMessageSent(sender_id=2, sender_name="P", channel_name="#osu", content="hi")
        assert a != b


# ===========================================================================
# PrivateMessageSent event
# ===========================================================================


class TestPrivateMessageSent:
    """Req 6.2: PrivateMessageSent domain event."""

    def test_is_subclass_of_event(self) -> None:
        assert issubclass(PrivateMessageSent, Event)

    def test_instance_is_event(self) -> None:
        event = PrivateMessageSent(
            sender_id=1,
            sender_name="Sender",
            target_id=2,
            target_name="Target",
            content="hello",
        )
        assert isinstance(event, Event)

    def test_frozen(self) -> None:
        event = PrivateMessageSent(
            sender_id=1,
            sender_name="Sender",
            target_id=2,
            target_name="Target",
            content="hello",
        )
        assert_rejects_setattr(event, "sender_id", 2)

    def test_slots_enabled(self) -> None:
        assert hasattr(PrivateMessageSent, "__slots__")

    def test_fields(self) -> None:
        field_names = {f.name for f in fields(PrivateMessageSent)}
        assert field_names == {"sender_id", "sender_name", "target_id", "target_name", "content"}

    def test_field_values(self) -> None:
        event = PrivateMessageSent(
            sender_id=10,
            sender_name="Alice",
            target_id=20,
            target_name="Bob",
            content="private hello",
        )
        assert event.sender_id == 10
        assert event.sender_name == "Alice"
        assert event.target_id == 20
        assert event.target_name == "Bob"
        assert event.content == "private hello"

    def test_equality(self) -> None:
        a = PrivateMessageSent(
            sender_id=1,
            sender_name="A",
            target_id=2,
            target_name="B",
            content="hi",
        )
        b = PrivateMessageSent(
            sender_id=1,
            sender_name="A",
            target_id=2,
            target_name="B",
            content="hi",
        )
        assert a == b

    def test_inequality(self) -> None:
        a = PrivateMessageSent(
            sender_id=1,
            sender_name="A",
            target_id=2,
            target_name="B",
            content="hi",
        )
        b = PrivateMessageSent(
            sender_id=1,
            sender_name="A",
            target_id=3,
            target_name="C",
            content="hi",
        )
        assert a != b


# ===========================================================================
# ChannelRoleOverride dataclass
# ===========================================================================


class TestChannelRoleOverride:
    """Discord-style role-based ACL override."""

    def test_slots_enabled(self) -> None:
        assert hasattr(ChannelRoleOverride, "__slots__")

    def test_creation(self) -> None:
        ov = ChannelRoleOverride(channel_id=1, role_id=2, can_read=True, can_write=False)
        assert ov.channel_id == 1
        assert ov.role_id == 2
        assert ov.can_read is True
        assert ov.can_write is False

    def test_fields(self) -> None:
        expected = {"channel_id", "role_id", "can_read", "can_write"}
        actual = {f.name for f in fields(ChannelRoleOverride)}
        assert actual == expected
