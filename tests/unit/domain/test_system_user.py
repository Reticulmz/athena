from __future__ import annotations

from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY, SystemUserIdentity
from tests.support.runtime_assertions import assert_rejects_setattr


class TestSystemUserIdentityDataclass:
    """Verify SystemUserIdentity dataclass contract."""

    def test_is_frozen(self) -> None:
        identity = SystemUserIdentity(user_id=1, username="BanchoBot")
        assert_rejects_setattr(identity, "user_id", 999)

    def test_is_slots(self) -> None:
        assert hasattr(SystemUserIdentity, "__slots__")

    def test_no_instance_dict(self) -> None:
        identity = SystemUserIdentity(user_id=1, username="BanchoBot")
        assert not hasattr(identity, "__dict__")

    def test_equals_by_value(self) -> None:
        a = SystemUserIdentity(user_id=1, username="BanchoBot")
        b = SystemUserIdentity(user_id=1, username="BanchoBot")
        assert a == b

    def test_not_equal_different_id(self) -> None:
        a = SystemUserIdentity(user_id=1, username="BanchoBot")
        b = SystemUserIdentity(user_id=2, username="BanchoBot")
        assert a != b

    def test_not_equal_different_username(self) -> None:
        a = SystemUserIdentity(user_id=1, username="BanchoBot")
        b = SystemUserIdentity(user_id=1, username="NotBanchoBot")
        assert a != b


class TestBanchoBotIdentity:
    """Verify BANCHO_BOT_IDENTITY is the single source of truth for BanchoBot."""

    def test_has_correct_user_id(self) -> None:
        assert BANCHO_BOT_IDENTITY.user_id == 1

    def test_has_correct_username(self) -> None:
        assert BANCHO_BOT_IDENTITY.username == "BanchoBot"

    def test_is_system_user_identity_instance(self) -> None:
        assert isinstance(BANCHO_BOT_IDENTITY, SystemUserIdentity)

    def test_is_immutable(self) -> None:
        assert_rejects_setattr(BANCHO_BOT_IDENTITY, "user_id", 999)
