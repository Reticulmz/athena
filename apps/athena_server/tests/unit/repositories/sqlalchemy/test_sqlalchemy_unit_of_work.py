"""SQLAlchemy command Unit of Workのtransaction境界を検証する."""

from __future__ import annotations

import ast
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, cast, override

import pytest
from tests.factories.domain import make_channel, make_user

from osu_server.domain.identity.friends import (
    FriendableSystemUserCatalog,
    FriendMutationStatus,
)
from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBestScope,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
    BeatmapPerformanceBestScope,
    UpsertBeatmapPerformanceBest,
)
from osu_server.repositories.sqlalchemy.commands import (
    SQLAlchemyBeatmapCommandRepository,
    SQLAlchemyBeatmapLeaderboardCommandRepository,
    SQLAlchemyBeatmapPerformanceBestCommandRepository,
    SQLAlchemyBlobCommandRepository,
    SQLAlchemyChannelCommandRepository,
    SQLAlchemyChatCommandRepository,
    SQLAlchemyCurrentUserStatsCommandRepository,
    SQLAlchemyFriendRelationshipCommandRepository,
    SQLAlchemyPersonalBestCommandRepository,
    SQLAlchemyReplayCommandRepository,
    SQLAlchemyRoleCommandRepository,
    SQLAlchemyScoreCommandRepository,
    SQLAlchemyScorePerformanceCommandRepository,
    SQLAlchemyScoreSubmissionCommandRepository,
    SQLAlchemyUserCommandRepository,
)
from osu_server.repositories.sqlalchemy.models.beatmap_leaderboard import (
    BeatmapLeaderboardUserBestModel,
)
from osu_server.repositories.sqlalchemy.models.channel import ChannelModel
from osu_server.repositories.sqlalchemy.models.personal_best import PersonalBestModel
from osu_server.repositories.sqlalchemy.models.role import UserRoleModel
from osu_server.repositories.sqlalchemy.models.user import UserModel
from osu_server.repositories.sqlalchemy.models.user_stats import BeatmapPerformanceBestModel
from osu_server.repositories.sqlalchemy.unit_of_work import (
    SQLAlchemyCommandSessionFactory,
    SQLAlchemyUnitOfWorkFactory,
)
from osu_server.services.commands.identity import AddFriendCommand, AddFriendUseCase

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.base import Executable

PROJECT_ROOT = Path(__file__).parents[4]
COMMAND_ROOT = PROJECT_ROOT / "src" / "osu_server" / "repositories" / "sqlalchemy" / "commands"
_NOW = datetime(2026, 6, 14, tzinfo=UTC)


class FakeResult:
    """command repository readを再現するSQLAlchemy result test double.

    Attributes:
        _value (object | None): scalar_one_or_noneが返す設定値.
        _values (list[object]): scalars().all()が返す設定値群.
    """

    _value: object | None
    _values: list[object]

    def __init__(self, value: object | None = None, values: list[object] | None = None) -> None:
        """scalar値とscalar collectionを持つresult test doubleを初期化する.

        Args:
            value (object | None): scalar_one_or_noneから返す値.
            values (list[object] | None): scalars().all()から返す値群. Noneなら空list.
        """
        self._value = value
        self._values = values or []

    def scalar_one_or_none(self) -> object | None:
        """設定済みのscalar値を返す.

        Returns:
            object | None: 設定済みのscalar値. 値がない場合はNone.
        """
        return self._value

    def scalars(self) -> FakeResult:
        """Scalar collection access用にこのresultを返す.

        Returns:
            FakeResult: all()で設定済みの値群を返すこのtest double.
        """
        return self

    def all(self) -> list[object]:
        """設定済みのscalar値群を返す.

        Returns:
            list[object]: command repository readの結果として設定された値群.
        """
        return self._values


class FakeSession(AbstractAsyncContextManager["FakeSession"]):
    """transaction ownershipとcommand repository操作を記録するAsyncSession test double.

    Attributes:
        added (list[object]): addまたはmergeで受け取ったpersistence instance群.
        commits (int): commit呼び出し回数.
        rollbacks (int): rollback呼び出し回数.
        flushes (int): flush呼び出し回数.
        refreshed (list[object]): refreshで受け取ったpersistence instance群.
        closed (bool): closeが呼び出されたか.
        _next_user_id (int): flush時にUserModelへ割り当てる次のID.
        _next_channel_id (int): flush時にChannelModelへ割り当てる次のID.
        _next_personal_best_id (int): flush時にPersonalBestModelへ割り当てる次のID.
        _get_results (dict[tuple[type[object], object], object]): getのkey別設定結果.
        _execute_results (list[FakeResult]): executeごとに返す設定済みresult群.
        nested_transactions (int): begin_nestedで開始したSAVEPOINT数.

    Notes:
        repository内SAVEPOINTは記録だけ行う. commitとrollbackはUoWだけが所有する.
    """

    added: list[object]
    commits: int
    rollbacks: int
    flushes: int
    refreshed: list[object]
    closed: bool
    _next_user_id: int
    _next_channel_id: int
    _next_personal_best_id: int
    _get_results: dict[tuple[type[object], object], object]
    _execute_results: list[FakeResult]
    nested_transactions: int

    def __init__(
        self,
        *,
        get_results: dict[tuple[type[object], object], object] | None = None,
        execute_results: list[FakeResult] | None = None,
    ) -> None:
        """Command repository test用のsession状態と設定済みread結果を初期化する.

        Args:
            get_results (dict[tuple[type[object], object], object] | None): getのkey別応答値.
            execute_results (list[FakeResult] | None): executeごとに順番に返すresult群.
        """
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.refreshed = []
        self.closed = False
        self._next_user_id = 10
        self._next_channel_id = 20
        self._next_personal_best_id = 30
        self._get_results = get_results or {}
        self._execute_results = execute_results or []
        self.nested_transactions = 0

    @override
    async def __aenter__(self) -> FakeSession:
        """context内で使用するtest sessionを返す.

        Returns:
            FakeSession: command repository操作を記録するこのsession.
        """
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """context終了時にtest sessionを閉じる.

        Args:
            exc_type (type[BaseException] | None): context内で送出された例外の型. 正常終了時はNone.
            exc (BaseException | None): context内で送出された例外. 正常終了時はNone.
            traceback (TracebackType | None): context内例外のtraceback. 正常終了時はNone.

        Returns:
            None: sessionを閉じて例外を抑制せずに完了する.
        """
        _ = exc_type
        _ = exc
        _ = traceback
        await self.close()

    async def get(self, model_type: type[object], identity: object) -> object | None:
        """model型とidentityに対応する設定済みread結果を返す.

        Args:
            model_type (type[object]): 取得対象のpersistence model型.
            identity (object): modelを識別するprimary keyまたはidentity値.

        Returns:
            object | None: keyに対応する設定値. 未設定時はNone.
        """
        return self._get_results.get((model_type, identity))

    async def execute(self, statement: Executable) -> FakeResult:
        """statementに対する次の設定済みresultを返す.

        Args:
            statement (Executable): command repositoryが実行するSQLAlchemy statement.

        Returns:
            FakeResult: 次の設定済みresult. 設定がなければ空result.
        """
        _ = statement
        if self._execute_results:
            return self._execute_results.pop(0)
        return FakeResult()

    @asynccontextmanager
    async def begin_nested(self) -> AsyncGenerator[None]:
        """Repository statement用のSAVEPOINT contextを提供する.

        Yields:
            None: nested transaction内でstatementを実行できる状態.

        Notes:
            test doubleはSAVEPOINTを実際には作成せず開始回数だけを記録する.
        """
        self.nested_transactions += 1
        yield

    async def merge(self, instance: object) -> object:
        """merge対象を追加済みinstanceとして記録し同じinstanceを返す.

        Args:
            instance (object): merge対象のpersistence instance.

        Returns:
            object: addedへ記録した入力instance.
        """
        self.added.append(instance)
        return instance

    def add(self, instance: object) -> None:
        """add対象をsessionの追加済みinstanceとして記録する.

        Args:
            instance (object): 追加するpersistence instance.

        Returns:
            None: instanceをaddedへ追加して呼び出し側へ値を返さずに完了する.
        """
        self.added.append(instance)

    def add_all(self, instances: Iterable[object]) -> None:
        """複数のadd対象をsessionの追加済みinstanceとして記録する.

        Args:
            instances (Iterable[object]): 追加するpersistence instance群.

        Returns:
            None: 全instanceをaddedへ追加して呼び出し側へ値を返さずに完了する.
        """
        self.added.extend(instances)

    async def delete(self, instance: object) -> None:
        """delete対象を追加済みinstance群から取り除く.

        Args:
            instance (object): 削除するpersistence instance.

        Returns:
            None: instanceをaddedから取り除いて呼び出し側へ値を返さずに完了する.

        Raises:
            ValueError: instanceがaddedに存在しない場合.
        """
        self.added.remove(instance)

    async def flush(self) -> None:
        """追加済みmodelへtest用IDとtimestampを割り当てる.

        Returns:
            None: flush回数を記録し未採番modelを更新して呼び出し側へ値を返さずに完了する.
        """
        self.flushes += 1
        for instance in self.added:
            if isinstance(instance, UserModel) and getattr(instance, "id", None) is None:
                instance.id = self._next_user_id
                self._next_user_id += 1
                instance.created_at = _NOW
                instance.updated_at = _NOW
                if getattr(instance, "latest_activity_at", None) is None:
                    instance.latest_activity_at = _NOW
            if isinstance(instance, ChannelModel) and getattr(instance, "id", None) is None:
                instance.id = self._next_channel_id
                self._next_channel_id += 1
                instance.created_at = _NOW
                instance.updated_at = _NOW
            if isinstance(instance, PersonalBestModel) and getattr(instance, "id", None) is None:
                instance.id = self._next_personal_best_id
                self._next_personal_best_id += 1
                instance.created_at = _NOW
                instance.updated_at = _NOW

    async def refresh(self, instance: object) -> None:
        """refresh対象を記録してrepositoryのreadback契約を検証可能にする.

        Args:
            instance (object): refresh対象のpersistence instance.

        Returns:
            None: instanceをrefreshedへ追加して呼び出し側へ値を返さずに完了する.
        """
        self.refreshed.append(instance)

    async def commit(self) -> None:
        """commit呼び出しを記録してUoWのtransaction ownershipを検証可能にする.

        Returns:
            None: commit回数を増加して呼び出し側へ値を返さずに完了する.
        """
        self.commits += 1

    async def rollback(self) -> None:
        """rollback呼び出しを記録してUoWのtransaction ownershipを検証可能にする.

        Returns:
            None: rollback回数を増加して呼び出し側へ値を返さずに完了する.
        """
        self.rollbacks += 1

    async def close(self) -> None:
        """sessionをclosed状態として記録する.

        Returns:
            None: closedをTrueにして呼び出し側へ値を返さずに完了する.
        """
        self.closed = True


class FakeSessionFactory:
    """同じtest sessionをcommand Unit of Workへ渡すsession factory test double.

    Attributes:
        _session (FakeSession): factoryが返すcommand session.
    """

    _session: FakeSession

    def __init__(self, session: FakeSession) -> None:
        """返却するtest sessionを持つfactory test doubleを初期化する.

        Args:
            session (FakeSession): Unit of Workへ渡すcommand test session.
        """
        self._session = session

    def __call__(self) -> AsyncSession:
        """設定済みtest sessionをAsyncSession型として返す.

        Returns:
            AsyncSession: Unit of Workがtransactionに使用するtest session.
        """
        return cast("AsyncSession", cast("object", self._session))


def _factory(session: FakeSession) -> SQLAlchemyUnitOfWorkFactory:
    """Test sessionをSQLAlchemy Unit of Work factoryへ型適合させて構築する.

    Args:
        session (FakeSession): command repository操作を記録するtest session.

    Returns:
        SQLAlchemyUnitOfWorkFactory: 指定sessionをscopeごとに返すUnit of Work factory.
    """
    session_factory = cast("SQLAlchemyCommandSessionFactory", FakeSessionFactory(session))
    return SQLAlchemyUnitOfWorkFactory(session_factory)


async def test_commit_persists_multi_repository_outcome_once_through_unit_of_work() -> None:
    """複数repositoryのmutationをUoWが1回だけcommitする契約を検証する.

    UserとChannelを同じscope内で作成しrepository内ではtransactionを確定せずUoW commit後に
    sessionが閉じることを確認する.

    Returns:
        None: 1回のcommitと作成modelとsession closeを検証して完了する.

    Raises:
        AssertionError: repositoryのmutation結果またはtransaction境界が異なる場合.
    """
    session = FakeSession()
    factory = _factory(session)
    source_latest_activity = datetime(2026, 6, 13, tzinfo=UTC)

    async with factory() as uow:
        created_user = await uow.users.create(
            make_user(
                username="SQL User",
                email="sql@example.com",
                created_at=source_latest_activity,
            )
        )
        created_channel = await uow.channels.create(make_channel(name="#sql"))

        assert created_user.id == 10
        assert created_user.latest_activity_at == source_latest_activity
        assert created_channel.id == 20
        assert session.commits == 0
        assert session.rollbacks == 0

        await uow.commit()

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True
    assert any(isinstance(model, UserModel) for model in session.added)
    assert any(isinstance(model, ChannelModel) for model in session.added)


async def test_exception_rolls_back_uncommitted_sqlalchemy_command_changes() -> None:
    """未commitのcommand mutation後の例外でUoWがrollbackする契約を検証する.

    User作成後にRuntimeErrorを送出しcommitなしでrollbackが1回だけ実行されsessionが閉じることを確認する.

    Returns:
        None: commit未実行とrollback回数とsession closeを検証して完了する.

    Raises:
        AssertionError: 例外後のtransaction境界またはsession lifecycleが異なる場合.
    """
    session = FakeSession()
    factory = _factory(session)

    with pytest.raises(RuntimeError, match="abort command"):
        await _raise_after_command_mutation(factory)

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed is True


async def test_unit_of_work_exposes_typed_sqlalchemy_command_repositories() -> None:
    """Entered UoWが全command portへ対応するSQLAlchemy repositoryを公開する契約を検証する.

    factoryからscopeをenterし全repository属性が期待するconcrete adapter型であることを確認する.

    Returns:
        None: 全command repositoryの型を検証して完了する.

    Raises:
        AssertionError: repository属性が不足するか期待するadapter型と異なる場合.
    """
    factory = _factory(FakeSession())

    async with factory() as uow:
        assert isinstance(uow.users, SQLAlchemyUserCommandRepository)
        assert isinstance(uow.roles, SQLAlchemyRoleCommandRepository)
        assert isinstance(uow.channels, SQLAlchemyChannelCommandRepository)
        assert isinstance(uow.chat, SQLAlchemyChatCommandRepository)
        assert isinstance(uow.friends, SQLAlchemyFriendRelationshipCommandRepository)
        assert isinstance(uow.scores, SQLAlchemyScoreCommandRepository)
        assert isinstance(uow.personal_bests, SQLAlchemyPersonalBestCommandRepository)
        assert isinstance(uow.submissions, SQLAlchemyScoreSubmissionCommandRepository)
        assert isinstance(uow.replays, SQLAlchemyReplayCommandRepository)
        assert isinstance(uow.blobs, SQLAlchemyBlobCommandRepository)
        assert isinstance(uow.beatmaps, SQLAlchemyBeatmapCommandRepository)
        assert isinstance(
            uow.beatmap_leaderboards,
            SQLAlchemyBeatmapLeaderboardCommandRepository,
        )
        assert isinstance(
            uow.beatmap_performance_bests,
            SQLAlchemyBeatmapPerformanceBestCommandRepository,
        )
        assert isinstance(uow.current_user_stats, SQLAlchemyCurrentUserStatsCommandRepository)
        assert isinstance(uow.score_performance, SQLAlchemyScorePerformanceCommandRepository)


async def test_beatmap_leaderboard_repository_commits_through_sqlalchemy_unit_of_work() -> None:
    """Leaderboard repositoryの変更をUoWだけがcommitする契約を検証する.

    既存projectionを返す設定済みsessionでupsertを実行し, repository内ではtransactionを確定せず
    UoW commit後にsessionが閉じることを確認する.

    Returns:
        None: repository内ではcommitせずUoW commitで1回だけ確定することを検証して完了する.

    Raises:
        AssertionError: repositoryがtransaction境界を所有する場合.
    """
    scope = _leaderboard_scope()
    session = FakeSession(
        execute_results=[
            FakeResult(),
            FakeResult(),
            FakeResult(),
            FakeResult(value=_leaderboard_model(scope=scope, score_id=90, score=1_000)),
        ]
    )
    factory = _factory(session)

    async with factory() as uow:
        created = await uow.beatmap_leaderboards.upsert_if_better(
            _leaderboard_upsert(scope=scope, score_id=90, score=1_000)
        )

        assert created.score_id == 90
        assert session.commits == 0
        assert session.rollbacks == 0

        await uow.commit()

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True


async def test_beatmap_leaderboard_repository_rolls_back_with_sqlalchemy_unit_of_work() -> None:
    """Leaderboard command失敗時にUoWが全変更をrollbackする契約を検証する.

    既存projectionを返す設定済みsessionでupsert後にRuntimeErrorを送出し, commitなしで
    rollbackが1回だけ実行されsessionが閉じることを確認する.

    Returns:
        None: repository更新後の例外でUoW rollbackが1回実行されることを検証して完了する.

    Raises:
        AssertionError: repositoryがrollbackするかUoW rollbackが実行されない場合.
    """
    scope = _leaderboard_scope()
    session = FakeSession(
        execute_results=[
            FakeResult(),
            FakeResult(),
            FakeResult(),
            FakeResult(value=_leaderboard_model(scope=scope, score_id=91, score=1_100)),
        ]
    )
    factory = _factory(session)

    with pytest.raises(RuntimeError, match="abort leaderboard command"):
        await _raise_after_leaderboard_mutation(factory, scope)

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed is True


async def test_beatmap_performance_best_repository_commits_through_uow() -> None:
    """Performance best repositoryのmutationをUoWだけがcommitする契約を検証する.

    performance best候補をupsertしrepository内ではcommitせずUoW commitで確定して
    sessionが閉じることを確認する.

    Returns:
        None: created rowと1回のcommitとsession closeを検証して完了する.

    Raises:
        AssertionError: upsert結果またはtransaction境界またはsession lifecycleが異なる場合.
    """
    scope = _performance_best_scope()
    session = FakeSession(
        execute_results=[
            FakeResult(),
            FakeResult(value=_performance_best_model(scope=scope, score_id=92, pp=Decimal("100"))),
        ]
    )
    factory = _factory(session)

    async with factory() as uow:
        created = await uow.beatmap_performance_bests.upsert_if_better(
            _performance_best_upsert(scope=scope, score_id=92, pp=Decimal("100"))
        )

        assert created.score_id == 92
        assert session.commits == 0
        assert session.rollbacks == 0

        await uow.commit()

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True


async def test_friend_command_repository_uses_returning_for_mutation_outcomes() -> None:
    """Friend relationship mutationがRETURNINGの有無をbool結果へ変換する契約を検証する.

    target存在確認とduplicate addとmissing removeを含む設定済みread結果を与え
    各mutation outcomeを確認する.

    Returns:
        None: target確認とaddとremoveのbool結果を検証して完了する.

    Raises:
        AssertionError: RETURNING結果から導くmutation outcomeが異なる場合.
    """
    session = FakeSession(
        execute_results=[
            FakeResult(value=2),
            FakeResult(value=2),
            FakeResult(value=None),
            FakeResult(value=2),
            FakeResult(value=None),
        ]
    )
    repo = SQLAlchemyFriendRelationshipCommandRepository(
        cast("AsyncSession", cast("object", session))
    )

    assert await repo.target_exists(2) is True
    assert await repo.add_relationship(owner_user_id=1, target_user_id=2) is True
    assert await repo.add_relationship(owner_user_id=1, target_user_id=2) is False
    assert await repo.remove_relationship(owner_user_id=1, target_user_id=2) is True
    assert await repo.remove_relationship(owner_user_id=1, target_user_id=2) is False


async def test_add_friend_use_case_commits_sqlalchemy_unit_of_work_insert() -> None:
    """AddFriendUseCaseがSQLAlchemy UoWのfriend insertをcommitする契約を検証する.

    存在するtarget userの設定結果でuse caseを実行しADDED outcomeとUoW所有のcommitを確認する.

    Returns:
        None: friend mutation statusと1回のcommitとsession closeを検証して完了する.

    Raises:
        AssertionError: use case outcomeまたはtransaction境界またはsession lifecycleが異なる場合.
    """
    session = FakeSession(
        execute_results=[
            FakeResult(value=2),
            FakeResult(value=2),
        ]
    )
    use_case = AddFriendUseCase(
        uow_factory=_factory(session),
        system_user_catalog=FriendableSystemUserCatalog.with_bancho_bot(),
    )

    result = await use_case.execute(
        AddFriendCommand(owner_user_id=1, target_user_id=2),
    )

    assert result.status is FriendMutationStatus.ADDED
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True


async def test_user_command_repository_updates_password_hash_without_commit() -> None:
    """User password hash mutationがflushだけを行いrepository内でcommitしない契約を検証する.

    既存UserModelを返すsessionでpassword hashを更新し更新結果とflush回数と
    transaction未確定を確認する.

    Returns:
        None: password hashとflush回数とcommit/rollback未実行を検証して完了する.

    Raises:
        AssertionError: password hash mutationまたはrepository transaction境界が異なる場合.
    """
    user = UserModel(
        id=3,
        username="SQLUser",
        safe_username="sqluser",
        email="sql@example.com",
        password_hash="old-hash",
        country="JP",
    )
    session = FakeSession(get_results={(UserModel, 3): user})
    repo = SQLAlchemyUserCommandRepository(cast("AsyncSession", cast("object", session)))

    updated = await repo.update_password_hash(3, "new-hash")

    assert updated is True
    assert user.password_hash == "new-hash"
    assert session.flushes == 1
    assert session.commits == 0
    assert session.rollbacks == 0


async def test_role_command_repository_replaces_roles_without_commit() -> None:
    """Role replacementがduplicate role IDを除去しrepository内でcommitしない契約を検証する.

    重複を含むrole ID列を渡し一意なUserRoleModel assignmentとflushだけが記録されることを確認する.

    Returns:
        None: role assignmentとflush回数とcommit/rollback未実行を検証して完了する.

    Raises:
        AssertionError: role assignmentまたはrepository transaction境界が異なる場合.
    """
    session = FakeSession()
    repo = SQLAlchemyRoleCommandRepository(cast("AsyncSession", cast("object", session)))

    await repo.set_roles_for_user(42, (3, 3, 1))

    assignments = [model for model in session.added if isinstance(model, UserRoleModel)]
    assert [(model.user_id, model.role_id) for model in assignments] == [
        (42, 3),
        (42, 1),
    ]
    assert session.flushes == 1
    assert session.commits == 0
    assert session.rollbacks == 0


def test_sqlalchemy_command_repositories_do_not_commit_or_rollback_per_method() -> None:
    """全SQLAlchemy command repositoryがmethod単位でcommitまたはrollbackしない契約を検証する.

    commands directory内のPython ASTを走査しcommitまたはrollback attribute callを収集して
    空であることを確認する.

    Returns:
        None: transaction境界違反がないことを検証して完了する.

    Raises:
        AssertionError: command repository sourceにcommitまたはrollback callが存在する場合.
    """
    violations: list[str] = []
    for path in sorted(COMMAND_ROOT.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in {"commit", "rollback"}:
                violations.append(f"{path.relative_to(PROJECT_ROOT)} calls {node.func.attr}()")

    assert violations == []


async def _raise_after_command_mutation(factory: SQLAlchemyUnitOfWorkFactory) -> None:
    """User mutation後に例外を送出してUoW rollback条件を作る.

    Args:
        factory (SQLAlchemyUnitOfWorkFactory): user repositoryを持つUoW scopeを生成するfactory.

    Returns:
        None: user mutation後に例外を送出して正常には値を返さない.

    Raises:
        RuntimeError: 未commit mutation後のrollback契約を検証するため常に送出する.
    """
    async with factory() as uow:
        _ = await uow.users.create(
            make_user(username="Rollback SQL", email="rollback-sql@example.com")
        )
        raise RuntimeError("abort command")


async def _raise_after_leaderboard_mutation(
    factory: SQLAlchemyUnitOfWorkFactory,
    scope: BeatmapLeaderboardUserBestScope,
) -> None:
    """Leaderboard mutation後に例外を送出してUoW rollback条件を作る.

    Args:
        factory (SQLAlchemyUnitOfWorkFactory): leaderboard repositoryを持つUoW scopeを生成する
            factory.
        scope (BeatmapLeaderboardUserBestScope): upsertするleaderboard projectionの完全一致scope.

    Returns:
        None: leaderboard mutation後に例外を送出して正常には値を返さない.

    Raises:
        RuntimeError: 未commit mutation後のrollback契約を検証するため常に送出する.
    """
    async with factory() as uow:
        _ = await uow.beatmap_leaderboards.upsert_if_better(
            _leaderboard_upsert(scope=scope, score_id=91, score=1_100)
        )
        raise RuntimeError("abort leaderboard command")


def _leaderboard_scope() -> BeatmapLeaderboardUserBestScope:
    """Leaderboard projection test用の完全一致scopeを構築する.

    Returns:
        BeatmapLeaderboardUserBestScope: 固定beatmapとuserとraw Modを持つscope.
    """
    return BeatmapLeaderboardUserBestScope(
        beatmap_id=1,
        beatmap_checksum="a" * 32,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        user_id=2,
        mods=ModCombination.none(),
    )


def _leaderboard_upsert(
    *,
    scope: BeatmapLeaderboardUserBestScope,
    score_id: int,
    score: int,
) -> UpsertBeatmapLeaderboardUserBest:
    """Leaderboard projectionのupsert commandをtest入力から構築する.

    Args:
        scope (BeatmapLeaderboardUserBestScope): projectionが所有する完全一致scope.
        score_id (int): projectionへ関連付けるscore ID.
        score (int): rank keyに使うscore値.

    Returns:
        UpsertBeatmapLeaderboardUserBest: 固定送信時刻を含むupsert command.
    """
    return UpsertBeatmapLeaderboardUserBest(
        scope=scope,
        score_id=score_id,
        rank_key=ScoreRankKey(score=score, submitted_at=_NOW, score_id=score_id),
    )


def _leaderboard_model(
    *,
    scope: BeatmapLeaderboardUserBestScope,
    score_id: int,
    score: int,
) -> BeatmapLeaderboardUserBestModel:
    """Repository read結果を再現するleaderboard projection modelを構築する.

    Args:
        scope (BeatmapLeaderboardUserBestScope): modelへ設定する完全一致scope.
        score_id (int): modelが参照するscore ID.
        score (int): modelのrank keyに使うscore値.

    Returns:
        BeatmapLeaderboardUserBestModel: fixed timestampを含むpersistence model.
    """
    return BeatmapLeaderboardUserBestModel(
        id=40,
        beatmap_id=scope.beatmap_id,
        beatmap_checksum=scope.beatmap_checksum,
        ruleset=scope.ruleset.value,
        playstyle=scope.playstyle.value,
        user_id=scope.user_id,
        mods=scope.mods.to_persistence_bitmask(),
        score_id=score_id,
        score=score,
        submitted_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _performance_best_scope() -> BeatmapPerformanceBestScope:
    """Performance best projection test用の完全一致scopeを構築する.

    Returns:
        BeatmapPerformanceBestScope: 固定userとbeatmapとmodeを持つscope.
    """
    return BeatmapPerformanceBestScope(
        user_id=2,
        beatmap_id=1,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
    )


def _performance_best_upsert(
    *,
    scope: BeatmapPerformanceBestScope,
    score_id: int,
    pp: Decimal,
) -> UpsertBeatmapPerformanceBest:
    """Performance best projectionのupsert commandをtest入力から構築する.

    Args:
        scope (BeatmapPerformanceBestScope): projectionが所有する完全一致scope.
        score_id (int): projectionへ関連付けるscore ID.
        pp (Decimal): rank keyに使うperformance point.

    Returns:
        UpsertBeatmapPerformanceBest: 固定accuracyとscoreと送信時刻を含むupsert command.
    """
    return UpsertBeatmapPerformanceBest(
        scope=scope,
        score_id=score_id,
        performance_calculation_id=score_id + 10_000,
        pp=pp,
        accuracy=0.98,
        score=1_000_000,
        submitted_at=_NOW,
    )


def _performance_best_model(
    *,
    scope: BeatmapPerformanceBestScope,
    score_id: int,
    pp: Decimal,
) -> BeatmapPerformanceBestModel:
    """Repository read結果を再現するperformance best projection modelを構築する.

    Args:
        scope (BeatmapPerformanceBestScope): modelへ設定する完全一致scope.
        score_id (int): modelが参照するscore ID.
        pp (Decimal): modelへ設定するperformance point.

    Returns:
        BeatmapPerformanceBestModel: fixed timestampを含むpersistence model.
    """
    return BeatmapPerformanceBestModel(
        id=41,
        user_id=scope.user_id,
        beatmap_id=scope.beatmap_id,
        ruleset=scope.ruleset.value,
        playstyle=scope.playstyle.value,
        score_id=score_id,
        performance_calculation_id=score_id + 10_000,
        pp=pp,
        accuracy=0.98,
        score=1_000_000,
        submitted_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )
