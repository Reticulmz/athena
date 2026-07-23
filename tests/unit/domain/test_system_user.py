"""System user identityとBanchoBot定数のdomain contractを検証するmodule."""

from __future__ import annotations

from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY, SystemUserIdentity
from tests.support.runtime_assertions import assert_rejects_setattr


class TestSystemUserIdentityDataclass:
    """SystemUserIdentityの不変dataclass contractを検証する."""

    def test_is_frozen(self) -> None:
        """作成済みidentityのuser IDを変更できないことを検証する.

        Returns:
            None: attribute代入拒否を検証して完了し,呼び出し側へ値を返さない.
        """
        identity = SystemUserIdentity(user_id=1, username="BanchoBot")
        assert_rejects_setattr(identity, "user_id", 999)

    def test_is_slots(self) -> None:
        """SystemUserIdentityがslotsを持つcompactな表現であることを検証する.

        Returns:
            None: slotsの存在を検証して完了し,呼び出し側へ値を返さない.
        """
        assert hasattr(SystemUserIdentity, "__slots__")

    def test_no_instance_dict(self) -> None:
        """Slots instanceが動的attribute用の__dict__を持たないことを検証する.

        Returns:
            None: instance dictionaryの不在を検証して完了し,呼び出し側へ値を返さない.
        """
        identity = SystemUserIdentity(user_id=1, username="BanchoBot")
        assert not hasattr(identity, "__dict__")

    def test_equals_by_value(self) -> None:
        """同じuser IDとusernameのidentityがvalue equalityを持つことを検証する.

        Returns:
            None: 同値instanceの比較結果を検証して完了し,呼び出し側へ値を返さない.
        """
        a = SystemUserIdentity(user_id=1, username="BanchoBot")
        b = SystemUserIdentity(user_id=1, username="BanchoBot")
        assert a == b

    def test_not_equal_different_id(self) -> None:
        """User IDが異なるidentityが非等価になることを検証する.

        Returns:
            None: ID差分の比較結果を検証して完了し,呼び出し側へ値を返さない.
        """
        a = SystemUserIdentity(user_id=1, username="BanchoBot")
        b = SystemUserIdentity(user_id=2, username="BanchoBot")
        assert a != b

    def test_not_equal_different_username(self) -> None:
        """Usernameが異なるidentityが非等価になることを検証する.

        Returns:
            None: name差分の比較結果を検証して完了し,呼び出し側へ値を返さない.
        """
        a = SystemUserIdentity(user_id=1, username="BanchoBot")
        b = SystemUserIdentity(user_id=1, username="NotBanchoBot")
        assert a != b


class TestBanchoBotIdentity:
    """BANCHO_BOT_IDENTITYがBanchoBotの唯一のidentity定数であることを検証する."""

    def test_has_correct_user_id(self) -> None:
        """BanchoBot定数が予約済みuser ID 1を持つことを検証する.

        Returns:
            None: user ID定数を検証して完了し,呼び出し側へ値を返さない.
        """
        assert BANCHO_BOT_IDENTITY.user_id == 1

    def test_has_correct_username(self) -> None:
        """BanchoBot定数が標準usernameを持つことを検証する.

        Returns:
            None: username定数を検証して完了し,呼び出し側へ値を返さない.
        """
        assert BANCHO_BOT_IDENTITY.username == "BanchoBot"

    def test_is_system_user_identity_instance(self) -> None:
        """BanchoBot定数がSystemUserIdentityとして公開されることを検証する.

        Returns:
            None: 定数のruntime typeを検証して完了し,呼び出し側へ値を返さない.
        """
        assert isinstance(BANCHO_BOT_IDENTITY, SystemUserIdentity)

    def test_is_immutable(self) -> None:
        """共有BanchoBot定数のuser IDを変更できないことを検証する.

        Returns:
            None: 定数の不変性を検証して完了し,呼び出し側へ値を返さない.
        """
        assert_rejects_setattr(BANCHO_BOT_IDENTITY, "user_id", 999)
