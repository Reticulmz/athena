"""Tests for UserRepository Protocol + InMemoryUserRepository."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.identity.users import User
from osu_server.repositories.interfaces.user_repository import UserRepository
from osu_server.repositories.memory.user_repository import InMemoryUserRepository


def _make_user(
    *,
    id: int = 0,  # noqa: A002
    username: str = "TestPlayer",
    email: str = "test@example.com",
    password_hash: str = "$argon2id$hash",
    country: str = "JP",
) -> User:
    """Create a User with sensible defaults for testing."""
    now = datetime.now(UTC)
    return User(
        id=id,
        username=username,
        safe_username=User.normalize_username(username),
        email=email,
        password_hash=password_hash,
        country=country,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def repo() -> InMemoryUserRepository:
    return InMemoryUserRepository()


class TestProtocolConformance:
    """InMemoryUserRepository satisfies UserRepository Protocol at runtime."""

    def test_is_instance_of_protocol(self, repo: InMemoryUserRepository) -> None:
        assert isinstance(repo, UserRepository)


class TestCreate:
    """create() stores a user and returns it with an auto-generated id."""

    async def test_returns_user_with_generated_id(self, repo: InMemoryUserRepository) -> None:
        user = _make_user()

        created = await repo.create(user)

        assert created.id > 0
        assert created.username == "TestPlayer"
        assert created.safe_username == "testplayer"

    async def test_preserves_all_fields(self, repo: InMemoryUserRepository) -> None:
        user = _make_user(email="peppy@ppy.sh", country="AU")

        created = await repo.create(user)

        assert created.email == "peppy@ppy.sh"
        assert created.country == "AU"
        assert created.password_hash == "$argon2id$hash"

    async def test_auto_increment_ids(self, repo: InMemoryUserRepository) -> None:
        user_a = await repo.create(_make_user(username="PlayerA", email="a@test.com"))
        user_b = await repo.create(_make_user(username="PlayerB", email="b@test.com"))

        # ID 1 is reserved for the BanchoBot system user.
        assert user_a.id == 2
        assert user_b.id == 3

    async def test_duplicate_safe_username_raises(self, repo: InMemoryUserRepository) -> None:
        _ = await repo.create(_make_user(username="TestPlayer"))

        with pytest.raises(ValueError, match="safe_username"):
            _ = await repo.create(_make_user(username="testplayer", email="other@test.com"))

    async def test_duplicate_email_raises(self, repo: InMemoryUserRepository) -> None:
        _ = await repo.create(_make_user(email="taken@test.com"))

        with pytest.raises(ValueError, match="email"):
            _ = await repo.create(_make_user(username="OtherPlayer", email="taken@test.com"))


class TestGetById:
    """get_by_id() retrieves a user by primary key."""

    async def test_found(self, repo: InMemoryUserRepository) -> None:
        created = await repo.create(_make_user())

        result = await repo.get_by_id(created.id)

        assert result is not None
        assert result.id == created.id
        assert result.username == "TestPlayer"

    async def test_not_found_returns_none(self, repo: InMemoryUserRepository) -> None:
        result = await repo.get_by_id(9999)

        assert result is None


class TestGetBySafeUsername:
    """get_by_safe_username() retrieves a user by normalized username."""

    async def test_found(self, repo: InMemoryUserRepository) -> None:
        _ = await repo.create(_make_user(username="Cool Player"))

        result = await repo.get_by_safe_username("cool_player")

        assert result is not None
        assert result.username == "Cool Player"

    async def test_case_insensitive(self, repo: InMemoryUserRepository) -> None:
        """Lookup is case-insensitive since safe_username is already normalized."""
        _ = await repo.create(_make_user(username="TestPlayer"))

        result = await repo.get_by_safe_username("TESTPLAYER")

        assert result is not None
        assert result.safe_username == "testplayer"

    async def test_not_found_returns_none(self, repo: InMemoryUserRepository) -> None:
        result = await repo.get_by_safe_username("nonexistent")

        assert result is None


class TestGetByEmail:
    """get_by_email() retrieves a user by email address."""

    async def test_found(self, repo: InMemoryUserRepository) -> None:
        _ = await repo.create(_make_user(email="peppy@ppy.sh"))

        result = await repo.get_by_email("peppy@ppy.sh")

        assert result is not None
        assert result.email == "peppy@ppy.sh"

    async def test_case_insensitive(self, repo: InMemoryUserRepository) -> None:
        """Email lookup should be case-insensitive."""
        _ = await repo.create(_make_user(email="Peppy@PPY.sh"))

        result = await repo.get_by_email("peppy@ppy.sh")

        assert result is not None
        assert result.email == "Peppy@PPY.sh"

    async def test_not_found_returns_none(self, repo: InMemoryUserRepository) -> None:
        result = await repo.get_by_email("nobody@test.com")

        assert result is None


class TestIsUsernameDisallowed:
    """is_username_disallowed() checks the disallowed username list."""

    async def test_not_disallowed_by_default(self, repo: InMemoryUserRepository) -> None:
        result = await repo.is_username_disallowed("testplayer")

        assert result is False

    async def test_disallowed_after_add(self, repo: InMemoryUserRepository) -> None:
        await repo.add_disallowed_username("badname")

        result = await repo.is_username_disallowed("badname")

        assert result is True

    async def test_case_insensitive(self, repo: InMemoryUserRepository) -> None:
        """Disallowed check is case-insensitive."""
        await repo.add_disallowed_username("BadName")

        assert await repo.is_username_disallowed("badname") is True
        assert await repo.is_username_disallowed("BADNAME") is True

    async def test_add_duplicate_is_idempotent(self, repo: InMemoryUserRepository) -> None:
        await repo.add_disallowed_username("badname")
        await repo.add_disallowed_username("badname")

        assert await repo.is_username_disallowed("badname") is True
