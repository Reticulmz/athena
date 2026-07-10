from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

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
            "latest_activity_at",
        }
        assert field_names == expected

    def test_latest_activity_defaults_to_created_at(self) -> None:
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
