"""role command repository memory adapterのcontractを検証するtest module."""

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
    """検証用Roleを既定値付きで組み立てる.

    Args:
        id (int): repositoryへ保存するrole ID. 既定値は未永続化を表す0.
        name (str): roleを識別する表示名.
        permissions (Privileges): roleに割り当てるauthorization capability集合.
        position (int): role一覧で使う昇順の並び順.

    Returns:
        Role: 指定値とtest用既定値を持つrole.
    """
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
    """既定roleをseedしたmemory command repositoryを提供する.

    Returns:
        InMemoryRoleCommandRepository: Default/Moderator/Admin roleを持つ独立したrepository.
    """
    repository = InMemoryRoleCommandRepository(InMemoryCommandRepositoryState())
    for role in _SEED_ROLES:
        repository.add_role(role)
    return repository


@pytest.fixture
def empty_repo() -> InMemoryRoleCommandRepository:
    """roleが未登録のmemory command repositoryを提供する.

    Returns:
        InMemoryRoleCommandRepository: default role不在の条件を検証する空repository.
    """
    return InMemoryRoleCommandRepository(InMemoryCommandRepositoryState())


class TestProtocolConformance:
    """memory role repositoryのruntime Protocol適合を検証するtest群."""

    def test_is_instance_of_protocol(self, repo: InMemoryRoleCommandRepository) -> None:
        """seed済みmemory adapterがRoleCommandRepositoryとして認識されることを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): Protocol適合を確認するmemory adapter fixture.

        Returns:
            None: runtime Protocol判定を検証して完了し, 呼び出し側へ値を返さない.
        """
        assert isinstance(repo, RoleCommandRepository)


class TestGetById:
    """role IDによる取得contractを検証するtest群."""

    async def test_found(self, repo: InMemoryRoleCommandRepository) -> None:
        """登録済みroleをprimary keyで取得できることを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): seed済みroleを検索するmemory adapter fixture.

        Returns:
            None: 取得結果のIDとnameを検証して完了し, 呼び出し側へ値を返さない.
        """
        result = await repo.get_by_id(1)

        assert result is not None
        assert result.id == 1
        assert result.name == "Default"

    async def test_not_found_returns_none(self, repo: InMemoryRoleCommandRepository) -> None:
        """未登録role IDの取得がNoneを返すことを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): 未登録IDを照会するmemory adapter fixture.

        Returns:
            None: 欠損resultを検証して完了し, 呼び出し側へ値を返さない.
        """
        result = await repo.get_by_id(9999)

        assert result is None


class TestGetByName:
    """role nameによる取得contractを検証するtest群."""

    async def test_found(self, repo: InMemoryRoleCommandRepository) -> None:
        """登録済みroleをnameで取得できることを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): seed済みroleを検索するmemory adapter fixture.

        Returns:
            None: 取得結果のIDとnameを検証して完了し, 呼び出し側へ値を返さない.
        """
        result = await repo.get_by_name("Moderator")

        assert result is not None
        assert result.id == 2
        assert result.name == "Moderator"

    async def test_not_found_returns_none(self, repo: InMemoryRoleCommandRepository) -> None:
        """未登録role nameの取得がNoneを返すことを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): 未登録nameを照会するmemory adapter fixture.

        Returns:
            None: 欠損resultを検証して完了し, 呼び出し側へ値を返さない.
        """
        result = await repo.get_by_name("Nonexistent")

        assert result is None


class TestGetRolesForUser:
    """userへ割り当てたrole一覧の取得contractを検証するtest群."""

    async def test_no_roles_returns_empty_list(self, repo: InMemoryRoleCommandRepository) -> None:
        """role未割当userの取得が空listを返すことを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): role未割当userを照会するmemory adapter fixture.

        Returns:
            None: 空のrole一覧を検証して完了し, 呼び出し側へ値を返さない.
        """
        result = await repo.get_roles_for_user(user_id=1)

        assert result == []

    async def test_single_role(self, repo: InMemoryRoleCommandRepository) -> None:
        """1件のrole割当が同じuserの一覧に現れることを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): roleを割当して取得するmemory adapter fixture.

        Returns:
            None: 割当済みroleだけを含む一覧を検証して完了し, 呼び出し側へ値を返さない.
        """
        await repo.assign_role(user_id=1, role_id=1)

        result = await repo.get_roles_for_user(user_id=1)

        assert len(result) == 1
        assert result[0].name == "Default"

    async def test_multiple_roles_sorted_by_position_ascending(
        self, repo: InMemoryRoleCommandRepository
    ) -> None:
        """複数roleが割当順ではなくposition昇順で返ることを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): 逆順にroleを割当するmemory adapter fixture.

        Returns:
            None: Default/Moderator/Adminのposition順を検証して完了し, 呼び出し側へ値を返さない.
        """
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
        """userごとのrole割当が相互に混在しないことを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): 別userへ異なるroleを割当するfixture.

        Returns:
            None: 各userが自身に割当済みroleだけを取得することを検証して完了する.
        """
        await repo.assign_role(user_id=1, role_id=1)
        await repo.assign_role(user_id=2, role_id=2)

        user1_roles = await repo.get_roles_for_user(user_id=1)
        user2_roles = await repo.get_roles_for_user(user_id=2)

        assert len(user1_roles) == 1
        assert user1_roles[0].name == "Default"
        assert len(user2_roles) == 1
        assert user2_roles[0].name == "Moderator"


class TestAssignRole:
    """userへのrole割当command contractを検証するtest群."""

    async def test_assign_and_retrieve(self, repo: InMemoryRoleCommandRepository) -> None:
        """割当済みroleを同じuserの一覧から取得できることを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): roleを割当して取得するmemory adapter fixture.

        Returns:
            None: 取得したrole IDが割当値と一致することを検証して完了し, 呼び出し側へ値を返さない.
        """
        await repo.assign_role(user_id=1, role_id=2)

        roles = await repo.get_roles_for_user(user_id=1)

        assert len(roles) == 1
        assert roles[0].id == 2

    async def test_assign_duplicate_is_idempotent(
        self, repo: InMemoryRoleCommandRepository
    ) -> None:
        """同じroleの重複割当が一覧を重複させないことを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): 同一roleを2回割当するmemory adapter fixture.

        Returns:
            None: role一覧が1件に保たれることを検証して完了し, 呼び出し側へ値を返さない.
        """
        await repo.assign_role(user_id=1, role_id=1)
        await repo.assign_role(user_id=1, role_id=1)

        roles = await repo.get_roles_for_user(user_id=1)

        assert len(roles) == 1


class TestGetDefaultRole:
    """default role取得contractを検証するtest群."""

    async def test_returns_default_role(self, repo: InMemoryRoleCommandRepository) -> None:
        """Default roleがnameとpermissionを保って取得されることを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): Default roleをseedしたmemory adapter fixture.

        Returns:
            None: default roleの識別値を検証して完了し, 呼び出し側へ値を返さない.
        """
        result = await repo.get_default_role()

        assert result.name == "Default"
        assert result.permissions == Privileges.NORMAL

    async def test_raises_when_no_default_role(
        self, empty_repo: InMemoryRoleCommandRepository
    ) -> None:
        """Default role不在時に取得がLookupErrorを送出することを検証する.

        Args:
            empty_repo (InMemoryRoleCommandRepository): Default role不在のfixture.

        Returns:
            None: callerが扱う欠損errorを検証して完了し, 呼び出し側へ値を返さない.
        """
        with pytest.raises(LookupError, match="Default"):
            _ = await empty_repo.get_default_role()


class TestGetUserIdsForRoleProtocol:
    """roleからuser IDを取得するProtocol contractを検証するtest群."""

    def test_protocol_declares_method(self) -> None:
        """RoleCommandRepositoryがuser ID取得methodを宣言することを検証する.

        Returns:
            None: Protocol attributeの存在を検証して完了し, 呼び出し側へ値を返さない.
        """
        assert hasattr(RoleCommandRepository, "get_user_ids_for_role")

    def test_memory_impl_satisfies_protocol(self, repo: InMemoryRoleCommandRepository) -> None:
        """実装adapterがuser ID取得を含むProtocolに適合することを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): runtime Protocol判定を行うmemory adapter fixture.

        Returns:
            None: adapterのProtocol適合を検証して完了し, 呼び出し側へ値を返さない.
        """
        assert isinstance(repo, RoleCommandRepository)


class TestGetUserIdsForRole:
    """roleへ割り当てたuser ID一覧の取得contractを検証するtest群."""

    async def test_returns_user_ids_for_role(self, repo: InMemoryRoleCommandRepository) -> None:
        """同じroleのuser IDが昇順で取得されることを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): 3 userへ同一roleを割当するmemory adapter fixture.

        Returns:
            None: 割当user IDの昇順一覧を検証して完了し, 呼び出し側へ値を返さない.
        """
        await repo.assign_role(user_id=1, role_id=2)
        await repo.assign_role(user_id=3, role_id=2)
        await repo.assign_role(user_id=2, role_id=2)

        result = await repo.get_user_ids_for_role(role_id=2)

        assert result == [1, 2, 3]

    async def test_returns_empty_for_unassigned_role(
        self, repo: InMemoryRoleCommandRepository
    ) -> None:
        """割当のないroleのuser ID取得が空listを返すことを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): 未割当roleを照会するmemory adapter fixture.

        Returns:
            None: 空のuser ID一覧を検証して完了し, 呼び出し側へ値を返さない.
        """
        result = await repo.get_user_ids_for_role(role_id=9999)

        assert result == []

    async def test_excludes_users_with_other_roles(
        self, repo: InMemoryRoleCommandRepository
    ) -> None:
        """他roleだけを持つuserが対象roleの一覧から除外されることを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): 異なるroleを各userへ割当するfixture.

        Returns:
            None: 対象roleを持つuserだけが残ることを検証して完了し, 呼び出し側へ値を返さない.
        """
        await repo.assign_role(user_id=1, role_id=1)  # Default
        await repo.assign_role(user_id=2, role_id=2)  # Moderator
        await repo.assign_role(user_id=3, role_id=1)  # Default

        result = await repo.get_user_ids_for_role(role_id=2)

        assert result == [2]  # Only user 2 has Moderator

    async def test_returns_sorted_ascending(self, repo: InMemoryRoleCommandRepository) -> None:
        """非昇順に割当してもuser ID一覧が昇順で返ることを検証する.

        Args:
            repo (InMemoryRoleCommandRepository): 非昇順IDを同じroleへ割当するfixture.

        Returns:
            None: 数値昇順のuser ID一覧を検証して完了し, 呼び出し側へ値を返さない.
        """
        # Assign in non-sorted order
        await repo.assign_role(user_id=100, role_id=1)
        await repo.assign_role(user_id=1, role_id=1)
        await repo.assign_role(user_id=50, role_id=1)

        result = await repo.get_user_ids_for_role(role_id=1)

        assert result == [1, 50, 100]

    async def test_empty_repo_returns_empty(
        self, empty_repo: InMemoryRoleCommandRepository
    ) -> None:
        """role未登録repositoryのuser ID取得が空listを返すことを検証する.

        Args:
            empty_repo (InMemoryRoleCommandRepository): role assignmentがないfixture.

        Returns:
            None: 空のuser ID一覧を検証して完了し, 呼び出し側へ値を返さない.
        """
        result = await empty_repo.get_user_ids_for_role(role_id=1)

        assert result == []
