from __future__ import annotations

from dataclasses import fields

from osu_server.domain.identity.users import User


class TestNormalizeUsername:
    def test_lowercase(self) -> None:
        assert User.normalize_username("PlayerName") == "playername"

    def test_space_to_underscore(self) -> None:
        assert User.normalize_username("Player Name") == "player_name"

    def test_mixed_case_and_spaces(self) -> None:
        assert User.normalize_username("Cool Player") == "cool_player"

    def test_already_normalized(self) -> None:
        assert User.normalize_username("player_name") == "player_name"

    def test_uppercase_with_underscore(self) -> None:
        assert User.normalize_username("Player_Name") == "player_name"

    def test_hyphen_preserved(self) -> None:
        assert User.normalize_username("player-name") == "player-name"

    def test_single_char(self) -> None:
        assert User.normalize_username("A") == "a"

    def test_all_spaces(self) -> None:
        assert User.normalize_username("a b c") == "a_b_c"


class TestUserDataclass:
    def test_slots(self) -> None:
        assert hasattr(User, "__slots__")

    def test_fields(self) -> None:
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
        }
        assert field_names == expected
