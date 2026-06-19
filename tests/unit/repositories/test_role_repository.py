"""Tests for the role command repository memory adapter."""

from __future__ import annotations

import pytest

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.repositories.interfaces.commands.roles import RoleCommandRepository
from osu_server.repositories.memory.commands.roles import InMemoryRoleCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


def _make_role(
    *,
    id: int = 0,  # noqa: A002
    name: str = "Default",
    permissions: Privileges = Privileges.NORMAL,
    position: int = 0,
) -> Role:
    """Create a Role with sensible defaults for testing."""
    return Role(id=id, name=name, permissions=permissions, position=position)


_SEED_ROLES: list[Role] = [
    _make_role(id=1, name="Default", permissions=Privileges.NORMAL, position=0),
    _make_role(
        id=2,
        name="Moderator",
        permissions=Privileges.NORMAL | Privileges.MODERATOR,
        position=10,
    ),
    _make_role(id=3, name="Admin", permissions=Privileges.NORMAL | Privileges.ADMIN, position=20),
]


@pytest.fixture
def repo() -> InMemoryRoleCommandRepository:
    repository = InMemoryRoleCommandRepository(InMemoryCommandRepositoryState())
    for role in _SEED_ROLES:
        repository.add_role(role)
    return repository


@pytest.fixture
def empty_repo() -> InMemoryRoleCommandRepository:
    return InMemoryRoleCommandRepository(InMemoryCommandRepositoryState())


class TestProtocolConformance:
    """InMemoryRoleCommandRepository satisfies RoleCommandRepository at runtime."""

    def test_is_instance_of_protocol(self, repo: InMemoryRoleCommandRepository) -> None:
        assert isinstance(repo, RoleCommandRepository)


class TestGetById:
    """get_by_id() retrieves a role by primary key."""

    async def test_found(self, repo: InMemoryRoleCommandRepository) -> None:
        result = await repo.get_by_id(1)

        assert result is not None
        assert result.id == 1
        assert result.name == "Default"

    async def test_not_found_returns_none(self, repo: InMemoryRoleCommandRepository) -> None:
        result = await repo.get_by_id(9999)

        assert result is None


class TestGetByName:
    """get_by_name() retrieves a role by its name."""

    async def test_found(self, repo: InMemoryRoleCommandRepository) -> None:
        result = await repo.get_by_name("Moderator")

        assert result is not None
        assert result.id == 2
        assert result.name == "Moderator"

    async def test_not_found_returns_none(self, repo: InMemoryRoleCommandRepository) -> None:
        result = await repo.get_by_name("Nonexistent")

        assert result is None


class TestGetRolesForUser:
    """get_roles_for_user() returns roles assigned to a user, sorted by position ascending."""

    async def test_no_roles_returns_empty_list(self, repo: InMemoryRoleCommandRepository) -> None:
        result = await repo.get_roles_for_user(user_id=1)

        assert result == []

    async def test_single_role(self, repo: InMemoryRoleCommandRepository) -> None:
        await repo.assign_role(user_id=1, role_id=1)

        result = await repo.get_roles_for_user(user_id=1)

        assert len(result) == 1
        assert result[0].name == "Default"

    async def test_multiple_roles_sorted_by_position_ascending(
        self, repo: InMemoryRoleCommandRepository
    ) -> None:
        # Assign in reverse position order to verify sorting
        await repo.assign_role(user_id=1, role_id=3)  # Admin, position=20
        await repo.assign_role(user_id=1, role_id=1)  # Default, position=0
        await repo.assign_role(user_id=1, role_id=2)  # Moderator, position=10

        result = await repo.get_roles_for_user(user_id=1)

        assert len(result) == 3
        assert result[0].name == "Default"
        assert result[1].name == "Moderator"
        assert result[2].name == "Admin"

    async def test_different_users_have_independent_roles(
        self,
        repo: InMemoryRoleCommandRepository,
    ) -> None:
        await repo.assign_role(user_id=1, role_id=1)
        await repo.assign_role(user_id=2, role_id=2)

        user1_roles = await repo.get_roles_for_user(user_id=1)
        user2_roles = await repo.get_roles_for_user(user_id=2)

        assert len(user1_roles) == 1
        assert user1_roles[0].name == "Default"
        assert len(user2_roles) == 1
        assert user2_roles[0].name == "Moderator"


class TestAssignRole:
    """assign_role() stores user_id → role_id mappings."""

    async def test_assign_and_retrieve(self, repo: InMemoryRoleCommandRepository) -> None:
        await repo.assign_role(user_id=1, role_id=2)

        roles = await repo.get_roles_for_user(user_id=1)

        assert len(roles) == 1
        assert roles[0].id == 2

    async def test_assign_duplicate_is_idempotent(
        self, repo: InMemoryRoleCommandRepository
    ) -> None:
        await repo.assign_role(user_id=1, role_id=1)
        await repo.assign_role(user_id=1, role_id=1)

        roles = await repo.get_roles_for_user(user_id=1)

        assert len(roles) == 1


class TestGetDefaultRole:
    """get_default_role() returns the role named 'Default'."""

    async def test_returns_default_role(self, repo: InMemoryRoleCommandRepository) -> None:
        result = await repo.get_default_role()

        assert result.name == "Default"
        assert result.permissions == Privileges.NORMAL

    async def test_raises_when_no_default_role(
        self, empty_repo: InMemoryRoleCommandRepository
    ) -> None:
        with pytest.raises(LookupError, match="Default"):
            _ = await empty_repo.get_default_role()


class TestGetUserIdsForRoleProtocol:
    """get_user_ids_for_role() contract is declared on the Protocol."""

    def test_protocol_declares_method(self) -> None:
        assert hasattr(RoleCommandRepository, "get_user_ids_for_role")

    def test_memory_impl_satisfies_protocol(self, repo: InMemoryRoleCommandRepository) -> None:
        assert isinstance(repo, RoleCommandRepository)


class TestGetUserIdsForRole:
    """get_user_ids_for_role() returns assigned user IDs sorted ascending."""

    async def test_returns_user_ids_for_role(self, repo: InMemoryRoleCommandRepository) -> None:
        await repo.assign_role(user_id=1, role_id=2)
        await repo.assign_role(user_id=3, role_id=2)
        await repo.assign_role(user_id=2, role_id=2)

        result = await repo.get_user_ids_for_role(role_id=2)

        assert result == [1, 2, 3]

    async def test_returns_empty_for_unassigned_role(
        self, repo: InMemoryRoleCommandRepository
    ) -> None:
        result = await repo.get_user_ids_for_role(role_id=9999)

        assert result == []

    async def test_excludes_users_with_other_roles(
        self, repo: InMemoryRoleCommandRepository
    ) -> None:
        await repo.assign_role(user_id=1, role_id=1)  # Default
        await repo.assign_role(user_id=2, role_id=2)  # Moderator
        await repo.assign_role(user_id=3, role_id=1)  # Default

        result = await repo.get_user_ids_for_role(role_id=2)

        assert result == [2]  # Only user 2 has Moderator

    async def test_returns_sorted_ascending(self, repo: InMemoryRoleCommandRepository) -> None:
        # Assign in non-sorted order
        await repo.assign_role(user_id=100, role_id=1)
        await repo.assign_role(user_id=1, role_id=1)
        await repo.assign_role(user_id=50, role_id=1)

        result = await repo.get_user_ids_for_role(role_id=1)

        assert result == [1, 50, 100]

    async def test_empty_repo_returns_empty(
        self, empty_repo: InMemoryRoleCommandRepository
    ) -> None:
        result = await empty_repo.get_user_ids_for_role(role_id=1)

        assert result == []
