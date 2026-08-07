"""Role と permission flag の domain contract を検証する module."""

from __future__ import annotations

from osu_server.domain.compatibility.stable.permissions import BanchoClientPermission
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role


class TestPrivileges:
    """Server-side privilege flag の bitmask contract を検証する."""

    def test_each_flag_is_single_bit(self) -> None:
        """NONE以外の各 privilege が単一bitで表現されることを検証する.

        列挙した全memberを検査し,NONEは0,他はbit_countが1になる観測結果を確認する.

        Returns:
            None: flag表現を検証して完了し,呼び出し側へ値を返さない.
        """
        for member in Privileges:
            if member == Privileges.NONE:
                assert member.value == 0
            else:
                assert member.bit_count() == 1

    def test_flags_are_distinct(self) -> None:
        """異なる privilege が同一の整数値を共有しないことを検証する.

        NONEを除く全memberの値を収集し,重複がない観測結果を確認する.

        Returns:
            None: 値の一意性を検証して完了し,呼び出し側へ値を返さない.
        """
        values = [m.value for m in Privileges if m != Privileges.NONE]
        assert len(values) == len(set(values))

    def test_or_combination(self) -> None:
        """ORした privilege 集合が含むflagと含まないflagを区別することを検証する.

        NORMAL,VERIFIED,UNRESTRICTEDを結合し,ADMINだけが含まれない観測結果を確認する.

        Returns:
            None: flag結合契約を検証して完了し,呼び出し側へ値を返さない.
        """
        combined = Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED
        assert Privileges.NORMAL in combined
        assert Privileges.VERIFIED in combined
        assert Privileges.UNRESTRICTED in combined
        assert Privileges.ADMIN not in combined

    def test_default_role_permissions(self) -> None:
        """標準roleの3つの permission が正しいbit集合になることを検証する.

        標準permissionを結合し,各flagの所属とbit_countが3である観測結果を確認する.

        Returns:
            None: 標準permission集合を検証して完了し,呼び出し側へ値を返さない.
        """
        default_perms = Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED
        assert Privileges.NORMAL in default_perms
        assert Privileges.VERIFIED in default_perms
        assert Privileges.UNRESTRICTED in default_perms
        assert default_perms.bit_count() == 3

    def test_all_flags_combined(self) -> None:
        """全 privilege をORした集合が全memberを含むことを検証する.

        0から全memberを順に結合し,各memberが結果に所属する観測結果を確認する.

        Returns:
            None: 全flagの結合結果を検証して完了し,呼び出し側へ値を返さない.
        """
        all_flags = Privileges(0)
        for member in Privileges:
            all_flags |= member
        for member in Privileges:
            assert member in all_flags


class TestBanchoClientPermission:
    """Stable client向け permission flag の bitmask contract を検証する."""

    def test_each_flag_is_single_bit(self) -> None:
        """各 Bancho client permission が単一bitで表現されることを検証する.

        列挙した全memberのbit_countが1になる観測結果を確認する.

        Returns:
            None: flag表現を検証して完了し,呼び出し側へ値を返さない.
        """
        for member in BanchoClientPermission:
            assert member.bit_count() == 1

    def test_flags_are_distinct(self) -> None:
        """異なる Bancho client permission が同一値を共有しないことを検証する.

        全memberの整数値を収集し,集合化しても要素数が変わらない観測結果を確認する.

        Returns:
            None: 値の一意性を検証して完了し,呼び出し側へ値を返さない.
        """
        values = [m.value for m in BanchoClientPermission]
        assert len(values) == len(set(values))


class TestRoleDataclass:
    """Role value object のdataclass表現を検証する."""

    def test_slots(self) -> None:
        """Roleがslotsを持ち動的attributeを許さない表現であることを検証する.

        Role型を参照して__slots__ attributeの有無を調べ,slot定義が公開されていることを確認する.

        Returns:
            None: slotsの存在を検証して完了し,呼び出し側へ値を返さない.
        """
        assert hasattr(Role, "__slots__")

    def test_creation(self) -> None:
        """Role生成時に渡した識別子とpermissionがfieldへ保持されることを検証する.

        既知のroleを生成し,全constructor inputと対応するattributeの観測値を確認する.

        Returns:
            None: Role field値を検証して完了し,呼び出し側へ値を返さない.
        """
        role = Role(id=1, name="Default", permissions=Privileges.NORMAL, position=0)
        assert role.id == 1
        assert role.name == "Default"
        assert role.permissions == Privileges.NORMAL
        assert role.position == 0
