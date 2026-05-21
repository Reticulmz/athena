from __future__ import annotations

from osu_server.domain.role import ClientPermissions, Privileges, Role


class TestPrivileges:
    def test_each_flag_is_single_bit(self) -> None:
        for member in Privileges:
            if member == Privileges.NONE:
                assert member.value == 0
            else:
                assert member.bit_count() == 1

    def test_flags_are_distinct(self) -> None:
        values = [m.value for m in Privileges if m != Privileges.NONE]
        assert len(values) == len(set(values))

    def test_or_combination(self) -> None:
        combined = Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED
        assert Privileges.NORMAL in combined
        assert Privileges.VERIFIED in combined
        assert Privileges.UNRESTRICTED in combined
        assert Privileges.ADMIN not in combined

    def test_default_role_permissions(self) -> None:
        default_perms = Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED
        assert Privileges.NORMAL in default_perms
        assert Privileges.VERIFIED in default_perms
        assert Privileges.UNRESTRICTED in default_perms
        assert default_perms.bit_count() == 3  # noqa: PLR2004

    def test_all_flags_combined(self) -> None:
        all_flags = Privileges(0)
        for member in Privileges:
            all_flags |= member
        for member in Privileges:
            assert member in all_flags


class TestClientPermissions:
    def test_each_flag_is_single_bit(self) -> None:
        for member in ClientPermissions:
            assert member.bit_count() == 1

    def test_flags_are_distinct(self) -> None:
        values = [m.value for m in ClientPermissions]
        assert len(values) == len(set(values))


class TestRoleDataclass:
    def test_slots(self) -> None:
        assert hasattr(Role, "__slots__")

    def test_creation(self) -> None:
        role = Role(id=1, name="Default", permissions=Privileges.NORMAL, position=0)
        assert role.id == 1
        assert role.name == "Default"
        assert role.permissions == Privileges.NORMAL
        assert role.position == 0
