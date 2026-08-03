"""User name正規化とpersistent user dataclassのcontractを検証するmodule."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

from osu_server.domain.identity.users import User


class TestNormalizeUsername:
    """User.normalize_usernameの比較用name変換を検証する."""

    def test_lowercase(self) -> None:
        """大文字だけを含むuser nameがlowercase化されることを検証する.

        PlayerNameをnormalize_usernameへ渡し,全て小文字のplayernameが返ることを確認する.

        Returns:
            None: lowercase変換を検証して完了し,呼び出し側へ値を返さない.
        """
        assert User.normalize_username("PlayerName") == "playername"

    def test_space_to_underscore(self) -> None:
        """Spaceを含むuser nameがunderscoreへ置換されることを検証する.

        Player Nameをnormalize_usernameへ渡し,spaceがunderscoreへ変換された値を確認する.

        Returns:
            None: space置換を検証して完了し,呼び出し側へ値を返さない.
        """
        assert User.normalize_username("Player Name") == "player_name"

    def test_mixed_case_and_spaces(self) -> None:
        """大文字とspaceを混在させたnameが一度に正規化されることを検証する.

        Cool Playerをnormalize_usernameへ渡し,lowercase化とspace置換後の値を確認する.

        Returns:
            None: 複合変換を検証して完了し,呼び出し側へ値を返さない.
        """
        assert User.normalize_username("Cool Player") == "cool_player"

    def test_already_normalized(self) -> None:
        """既にsafe username形式の値が変化しないことを検証する.

        player_nameをnormalize_usernameへ渡し,既に正規化済みの入力と同じ値が返ることを確認する.

        Returns:
            None: 冪等な正規化を検証して完了し,呼び出し側へ値を返さない.
        """
        assert User.normalize_username("player_name") == "player_name"

    def test_uppercase_with_underscore(self) -> None:
        """Underscoreを保ちつつ大文字だけlowercase化することを検証する.

        Player_Nameをnormalize_usernameへ渡し,underscoreを保った小文字の値が返ることを確認する.

        Returns:
            None: underscore保持を検証して完了し,呼び出し側へ値を返さない.
        """
        assert User.normalize_username("Player_Name") == "player_name"

    def test_hyphen_preserved(self) -> None:
        """Hyphenを含むuser nameでhyphenが保持されることを検証する.

        player-nameをnormalize_usernameへ渡し,hyphenを含む入力と同じ値が返ることを確認する.

        Returns:
            None: hyphen保持を検証して完了し,呼び出し側へ値を返さない.
        """
        assert User.normalize_username("player-name") == "player-name"

    def test_single_char(self) -> None:
        """1文字の大文字user nameが対応する小文字へ変換されることを検証する.

        1文字のAをnormalize_usernameへ渡し,対応する小文字aが返ることを確認する.

        Returns:
            None: 最小長入力の変換を検証して完了し,呼び出し側へ値を返さない.
        """
        assert User.normalize_username("A") == "a"

    def test_all_spaces(self) -> None:
        """複数spaceを含むuser nameの全spaceがunderscoreへ変換されることを検証する.

        a b cをnormalize_usernameへ渡し,全てのspaceがunderscoreになった値を確認する.

        Returns:
            None: 複数spaceの変換を検証して完了し,呼び出し側へ値を返さない.
        """
        assert User.normalize_username("a b c") == "a_b_c"


class TestUserDataclass:
    """Persistent Userのfield layoutとactivity既定値を検証する."""

    def test_slots(self) -> None:
        """Userがslotsを持つdomain modelであることを検証する.

        User型を参照して__slots__ attributeの有無を調べ,slot定義が公開されていることを確認する.

        Returns:
            None: slotsの存在を検証して完了し,呼び出し側へ値を返さない.
        """
        assert hasattr(User, "__slots__")

    def test_fields(self) -> None:
        """Userのdataclass field集合がpersistent model contractと一致することを検証する.

        Userのdataclass field名を収集して永続modelの期待集合と比較し,両者が一致することを確認する.

        Returns:
            None: field名集合を検証して完了し,呼び出し側へ値を返さない.
        """
        field_names = {f.name for f in fields(User)}
        expected = {
            "id",
            "username",
            "safe_username",
            "email",
            "password_hash",
            "country",
            "created_at",
            "updated_at",
            "latest_activity_at",
        }
        assert field_names == expected

    def test_latest_activity_defaults_to_created_at(self) -> None:
        """Latest activity未指定時にcreated_atを使用することを検証する.

        異なるcreated_atとupdated_atを渡してuserを生成し,latest_activity_atがcreated_atになる観測結果を
        確認する.

        Returns:
            None: activity時刻の既定値を検証して完了し,呼び出し側へ値を返さない.
        """
        created_at = datetime(2026, 7, 7, 1, 2, 3, tzinfo=UTC)
        updated_at = datetime(2026, 7, 7, 4, 5, 6, tzinfo=UTC)

        user = User(
            id=1,
            username="TestPlayer",
            safe_username="testplayer",
            email="test@example.com",
            password_hash="hash",
            country="JP",
            created_at=created_at,
            updated_at=updated_at,
        )

        assert user.latest_activity_at == created_at
