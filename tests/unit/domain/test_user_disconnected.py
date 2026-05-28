"""Tests for UserDisconnected domain event.

Validates:
- Req 7.1: UserDisconnected inherits from Event base class
- Req 7.2: UserDisconnected is frozen (immutable) with slots=True
- Req 7.3: UserDisconnected holds user_id: int field
"""

from __future__ import annotations

from dataclasses import fields

from osu_server.domain.events import Event
from osu_server.domain.users.events import UserDisconnected
from tests.support import assert_rejects_setattr


class TestUserDisconnectedInheritance:
    """Req 7.1: UserDisconnected は Event 基底クラスを継承する。"""

    def test_is_subclass_of_event(self) -> None:
        assert issubclass(UserDisconnected, Event)

    def test_instance_is_event(self) -> None:
        event = UserDisconnected(user_id=1)
        assert isinstance(event, Event)


class TestUserDisconnectedImmutability:
    """Req 7.2: UserDisconnected は frozen=True で不変である。"""

    def test_frozen_raises_on_attribute_set(self) -> None:
        event = UserDisconnected(user_id=1)
        assert_rejects_setattr(event, "user_id", 2)

    def test_slots_enabled(self) -> None:
        assert hasattr(UserDisconnected, "__slots__")

    def test_no_dict(self) -> None:
        """slots=True のインスタンスは __dict__ を持たない。"""
        event = UserDisconnected(user_id=1)
        assert not hasattr(event, "__dict__")


class TestUserDisconnectedFields:
    """Req 7.3: UserDisconnected は user_id: int フィールドを持つ。"""

    def test_has_user_id_field(self) -> None:
        field_names = [f.name for f in fields(UserDisconnected)]
        assert "user_id" in field_names

    def test_user_id_type_annotation(self) -> None:
        field_map = {f.name: f for f in fields(UserDisconnected)}
        assert field_map["user_id"].type == "int"

    def test_user_id_value(self) -> None:
        event = UserDisconnected(user_id=42)
        assert event.user_id == 42  # noqa: PLR2004

    def test_equality(self) -> None:
        """同じ user_id を持つインスタンスは等価。"""
        a = UserDisconnected(user_id=1)
        b = UserDisconnected(user_id=1)
        assert a == b

    def test_inequality(self) -> None:
        a = UserDisconnected(user_id=1)
        b = UserDisconnected(user_id=2)
        assert a != b
