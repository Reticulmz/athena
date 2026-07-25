"""user command/query repository memory adapterのcontractを検証するtest module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.identity.users import User
from osu_server.repositories.interfaces.commands.users import UserCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.commands.users import InMemoryUserCommandRepository
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


def _make_user(
    *,
    id: int = 0,  # noqa: A002
    username: str = "TestPlayer",
    email: str = "test@example.com",
    password_hash: str = "$argon2id$hash",
    country: str = "JP",
    latest_activity_at: datetime | None = None,
) -> User:
    """検証用Userを既定値付きで組み立てる.

    Args:
        id (int): repositoryへ保存するuser ID. 既定値は未永続化を表す0.
        username (str): safe usernameの元になる表示名.
        email (str): uniquenessと取得を検証するemail address.
        password_hash (str): 永続化確認に使うpassword hash値.
        country (str): userのcountry code.
        latest_activity_at (datetime | None): 記録済みactivity時刻. 未指定時はNone.

    Returns:
        User: 現在時刻のcreated/updated値を持つ未永続化user.
    """
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
        latest_activity_at=latest_activity_at,
    )


@pytest.fixture
def command_state() -> InMemoryCommandRepositoryState:
    """各testで共有する空のmemory command stateを提供する.

    Returns:
        InMemoryCommandRepositoryState: test用の共有memory state.
    """
    return InMemoryCommandRepositoryState()


@pytest.fixture
def repo(command_state: InMemoryCommandRepositoryState) -> InMemoryUserCommandRepository:
    """共有stateへ書き込むuser command repositoryを提供する.

    Args:
        command_state (InMemoryCommandRepositoryState): fixture間で共有するmemory durable state.

    Returns:
        InMemoryUserCommandRepository: user commandを実行するmemory adapter.
    """
    return InMemoryUserCommandRepository(command_state)


@pytest.fixture
def query_repo(command_state: InMemoryCommandRepositoryState) -> InMemoryUserQueryRepository:
    """共有stateを読み出すuser query repositoryを提供する.

    Args:
        command_state (InMemoryCommandRepositoryState): command fixtureと共有するstate.

    Returns:
        InMemoryUserQueryRepository: command結果を観測するmemory query adapter.
    """
    return InMemoryUserQueryRepository(InMemoryUnitOfWorkFactory(command_state))


class TestProtocolConformance:
    """memory user repositoryのruntime Protocol適合を検証するtest群."""

    def test_is_instance_of_protocol(self, repo: InMemoryUserCommandRepository) -> None:
        """実装adapterがUserCommandRepositoryとして認識されることを検証する.

        Args:
            repo (InMemoryUserCommandRepository): Protocol適合を確認するmemory adapter fixture.

        Returns:
            None: runtime Protocol判定を検証して完了し, 呼び出し側へ値を返さない.
        """
        assert isinstance(repo, UserCommandRepository)


class TestCreate:
    """user作成commandの永続化/validation contractを検証するtest群."""

    async def test_returns_user_with_generated_id(
        self, repo: InMemoryUserCommandRepository
    ) -> None:
        """作成したuserに正のIDと正規化済みusernameが付与されることを検証する.

        Args:
            repo (InMemoryUserCommandRepository): userを作成するmemory command adapter fixture.

        Returns:
            None: 生成IDとusername fieldを検証して完了し, 呼び出し側へ値を返さない.
        """
        user = _make_user()

        created = await repo.create(user)

        assert created.id > 0
        assert created.username == "TestPlayer"
        assert created.safe_username == "testplayer"

    async def test_preserves_all_fields(self, repo: InMemoryUserCommandRepository) -> None:
        """作成commandが入力userの全fieldを保持することを検証する.

        Args:
            repo (InMemoryUserCommandRepository): field保持を検査するfixture.

        Returns:
            None: email/country/password/activity fieldを検証して完了し, 呼び出し側へ値を返さない.
        """
        user = _make_user(email="peppy@ppy.sh", country="AU")

        created = await repo.create(user)

        assert created.email == "peppy@ppy.sh"
        assert created.country == "AU"
        assert created.password_hash == "$argon2id$hash"
        assert created.latest_activity_at == user.latest_activity_at
        assert created.latest_activity_at is not None

    async def test_auto_increment_ids(self, repo: InMemoryUserCommandRepository) -> None:
        """予約済みID 1を除いた連番が作成順に採番されることを検証する.

        Args:
            repo (InMemoryUserCommandRepository): userを連続作成するfixture.

        Returns:
            None: 予約済みID 1を飛ばした連番を検証して完了し, 呼び出し側へ値を返さない.
        """
        user_a = await repo.create(_make_user(username="PlayerA", email="a@test.com"))
        user_b = await repo.create(_make_user(username="PlayerB", email="b@test.com"))

        # ID 1 is reserved for the BanchoBot system user.
        assert user_a.id == 2
        assert user_b.id == 3

    async def test_duplicate_safe_username_raises(
        self, repo: InMemoryUserCommandRepository
    ) -> None:
        """同じsafe usernameの作成がValueErrorで拒否されることを検証する.

        Args:
            repo (InMemoryUserCommandRepository): duplicate usernameを作成するfixture.

        Returns:
            None: safe_usernameを示すvalidation errorを検証して完了し, 呼び出し側へ値を返さない.
        """
        _ = await repo.create(_make_user(username="TestPlayer"))

        with pytest.raises(ValueError, match="safe_username"):
            _ = await repo.create(_make_user(username="testplayer", email="other@test.com"))

    async def test_duplicate_email_raises(self, repo: InMemoryUserCommandRepository) -> None:
        """同じemailの作成がValueErrorで拒否されることを検証する.

        Args:
            repo (InMemoryUserCommandRepository): duplicate emailを作成するfixture.

        Returns:
            None: emailを示すvalidation errorを検証して完了し, 呼び出し側へ値を返さない.
        """
        _ = await repo.create(_make_user(email="taken@test.com"))

        with pytest.raises(ValueError, match="email"):
            _ = await repo.create(_make_user(username="OtherPlayer", email="taken@test.com"))


class TestGetById:
    """user IDによるquery取得contractを検証するtest群."""

    async def test_found(
        self,
        repo: InMemoryUserCommandRepository,
        query_repo: InMemoryUserQueryRepository,
    ) -> None:
        """commandで作成したuserをquery adapterがIDで観測できることを検証する.

        Args:
            repo (InMemoryUserCommandRepository): 観測対象userを作成するfixture.
            query_repo (InMemoryUserQueryRepository): 作成結果をIDで照会するfixture.

        Returns:
            None: 取得userのIDとusernameを検証して完了し, 呼び出し側へ値を返さない.
        """
        created = await repo.create(_make_user())

        result = await query_repo.get_by_id(created.id)

        assert result is not None
        assert result.id == created.id
        assert result.username == "TestPlayer"

    async def test_not_found_returns_none(self, query_repo: InMemoryUserQueryRepository) -> None:
        """未登録user IDのquery取得がNoneを返すことを検証する.

        Args:
            query_repo (InMemoryUserQueryRepository): 未登録IDを照会するfixture.

        Returns:
            None: 欠損resultを検証して完了し, 呼び出し側へ値を返さない.
        """
        result = await query_repo.get_by_id(9999)

        assert result is None


class TestGetBySafeUsername:
    """safe usernameによるuser取得contractを検証するtest群."""

    async def test_found(self, repo: InMemoryUserCommandRepository) -> None:
        """正規化済みsafe usernameから元のuserを取得できることを検証する.

        Args:
            repo (InMemoryUserCommandRepository): userを作成し検索するfixture.

        Returns:
            None: 表示usernameを保持した取得resultを検証して完了し, 呼び出し側へ値を返さない.
        """
        _ = await repo.create(_make_user(username="Cool Player"))

        result = await repo.get_by_safe_username("cool_player")

        assert result is not None
        assert result.username == "Cool Player"

    async def test_case_insensitive(self, repo: InMemoryUserCommandRepository) -> None:
        """大文字入力でもsafe username lookupが成功することを検証する.

        Args:
            repo (InMemoryUserCommandRepository): 大文字入力で検索するfixture.

        Returns:
            None: 正規化済みsafe usernameを持つresultを検証して完了し, 呼び出し側へ値を返さない.
        """
        _ = await repo.create(_make_user(username="TestPlayer"))

        result = await repo.get_by_safe_username("TESTPLAYER")

        assert result is not None
        assert result.safe_username == "testplayer"

    async def test_not_found_returns_none(self, repo: InMemoryUserCommandRepository) -> None:
        """未登録safe usernameの取得がNoneを返すことを検証する.

        Args:
            repo (InMemoryUserCommandRepository): 未登録nameを照会するfixture.

        Returns:
            None: 欠損resultを検証して完了し, 呼び出し側へ値を返さない.
        """
        result = await repo.get_by_safe_username("nonexistent")

        assert result is None


class TestGetByEmail:
    """email addressによるuser取得contractを検証するtest群."""

    async def test_found(self, repo: InMemoryUserCommandRepository) -> None:
        """登録済みemail addressからuserを取得できることを検証する.

        Args:
            repo (InMemoryUserCommandRepository): userをemailで検索するfixture.

        Returns:
            None: 入力emailを保持した取得resultを検証して完了し, 呼び出し側へ値を返さない.
        """
        _ = await repo.create(_make_user(email="peppy@ppy.sh"))

        result = await repo.get_by_email("peppy@ppy.sh")

        assert result is not None
        assert result.email == "peppy@ppy.sh"

    async def test_case_insensitive(self, repo: InMemoryUserCommandRepository) -> None:
        """入力の大文字/小文字が異なってもemail lookupが成功することを検証する.

        Args:
            repo (InMemoryUserCommandRepository): mixed case emailのuserを作成して検索するfixture.

        Returns:
            None: 保存時のemail casingを保つresultを検証して完了し, 呼び出し側へ値を返さない.
        """
        _ = await repo.create(_make_user(email="Peppy@PPY.sh"))

        result = await repo.get_by_email("peppy@ppy.sh")

        assert result is not None
        assert result.email == "Peppy@PPY.sh"

    async def test_not_found_returns_none(self, repo: InMemoryUserCommandRepository) -> None:
        """未登録email addressの取得がNoneを返すことを検証する.

        Args:
            repo (InMemoryUserCommandRepository): 未登録emailを照会するfixture.

        Returns:
            None: 欠損resultを検証して完了し, 呼び出し側へ値を返さない.
        """
        result = await repo.get_by_email("nobody@test.com")

        assert result is None


class TestIsUsernameDisallowed:
    """disallowed username判定/登録contractを検証するtest群."""

    async def test_not_disallowed_by_default(self, repo: InMemoryUserCommandRepository) -> None:
        """未登録usernameが初期stateで許可されることを検証する.

        Args:
            repo (InMemoryUserCommandRepository): 初期stateを照会するfixture.

        Returns:
            None: 未登録nameのFalse判定を検証して完了し, 呼び出し側へ値を返さない.
        """
        result = await repo.is_username_disallowed("testplayer")

        assert result is False

    async def test_disallowed_after_add(self, repo: InMemoryUserCommandRepository) -> None:
        """登録したusernameがdisallowedとして判定されることを検証する.

        Args:
            repo (InMemoryUserCommandRepository): disallowed usernameを登録して照会するfixture.

        Returns:
            None: 登録済みnameのTrue判定を検証して完了し, 呼び出し側へ値を返さない.
        """
        await repo.add_disallowed_username("badname")

        result = await repo.is_username_disallowed("badname")

        assert result is True

    async def test_case_insensitive(self, repo: InMemoryUserCommandRepository) -> None:
        """入力の大文字/小文字が異なってもdisallowed username判定が成功することを検証する.

        Args:
            repo (InMemoryUserCommandRepository): mixed case nameを登録して照会するfixture.

        Returns:
            None: lowercase/uppercase入力がともにTrueになることを検証して完了する.
        """
        await repo.add_disallowed_username("BadName")

        assert await repo.is_username_disallowed("badname") is True
        assert await repo.is_username_disallowed("BADNAME") is True

    async def test_add_duplicate_is_idempotent(self, repo: InMemoryUserCommandRepository) -> None:
        """同じdisallowed usernameの重複登録が判定を壊さないことを検証する.

        Args:
            repo (InMemoryUserCommandRepository): 同じnameを2回登録するfixture.

        Returns:
            None: 重複後もnameがdisallowedであることを検証して完了し, 呼び出し側へ値を返さない.
        """
        await repo.add_disallowed_username("badname")
        await repo.add_disallowed_username("badname")

        assert await repo.is_username_disallowed("badname") is True


class TestTouchLatestActivity:
    """latest activity更新commandのscope/result contractを検証するtest群."""

    async def test_updates_only_target_user_latest_activity(
        self,
        repo: InMemoryUserCommandRepository,
        query_repo: InMemoryUserQueryRepository,
    ) -> None:
        """対象userのlatest activityだけを更新し他field/userを保つことを検証する.

        Args:
            repo (InMemoryUserCommandRepository): targetとother userを作成して更新するfixture.
            query_repo (InMemoryUserQueryRepository): 更新後stateを観測するfixture.

        Returns:
            None: targetだけのactivity更新と他field保持を検証して完了する.
        """
        old_activity = datetime(2026, 7, 1, tzinfo=UTC)
        new_activity = datetime(2026, 7, 2, tzinfo=UTC)
        target = await repo.create(
            _make_user(
                username="TargetUser",
                email="target@example.com",
                latest_activity_at=old_activity,
            )
        )
        other = await repo.create(
            _make_user(
                username="OtherUser",
                email="other@example.com",
                latest_activity_at=old_activity,
            )
        )

        touched = await repo.touch_latest_activity(target.id, new_activity)

        updated_target = await query_repo.get_by_id(target.id)
        unchanged_other = await query_repo.get_by_id(other.id)
        assert touched is True
        assert updated_target is not None
        assert unchanged_other is not None
        assert updated_target.latest_activity_at == new_activity
        assert updated_target.created_at == target.created_at
        assert updated_target.updated_at == target.updated_at
        assert unchanged_other.latest_activity_at == old_activity

    async def test_returns_false_when_user_missing(
        self, repo: InMemoryUserCommandRepository
    ) -> None:
        """未登録userのlatest activity更新がFalseを返すことを検証する.

        Args:
            repo (InMemoryUserCommandRepository): 未登録IDを更新するfixture.

        Returns:
            None: stateを作らずFalseで完了することを検証し, 呼び出し側へ値を返さない.
        """
        touched = await repo.touch_latest_activity(999, datetime(2026, 7, 2, tzinfo=UTC))

        assert touched is False
