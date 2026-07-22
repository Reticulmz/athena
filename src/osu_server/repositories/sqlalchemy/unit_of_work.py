"""SQLAlchemy command repositoryのtransaction境界を実装する.

1つのUnit of Work scopeは全command repositoryへ同じAsyncSessionを渡す.
commit/rollbackとcloseを一元管理する.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

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

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncSession

    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork


class SQLAlchemyCommandSessionFactory(Protocol):
    """SQLAlchemy command Unit of Workが要求するsession factory契約を表す."""

    def __call__(self) -> AsyncSession:
        """新しいcommand transaction用AsyncSessionを生成する.

        Returns:
            AsyncSession: Unit of Workがrepositoryをbindする未closeのsession.
        """
        ...


class SQLAlchemyUnitOfWorkFactory:
    """SQLAlchemy command Unit of Work scopeを生成するfactoryを表す.

    Attributes:
        _session_factory (SQLAlchemyCommandSessionFactory):
            scopeごとにAsyncSessionを生成するfactory.
    """

    def __init__(self, session_factory: SQLAlchemyCommandSessionFactory) -> None:
        """scopeごとに使うAsyncSession factoryを保持する.

        Args:
            session_factory (SQLAlchemyCommandSessionFactory):
                command transaction用sessionを生成するfactory.

        """
        self._session_factory: SQLAlchemyCommandSessionFactory = session_factory

    def __call__(self) -> AbstractAsyncContextManager[UnitOfWork]:
        """未enterの新しいSQLAlchemy Unit of Workを返す.

        Returns:
            AbstractAsyncContextManager[UnitOfWork]: async withでtransaction境界を開始できるscope.

        Notes:
            呼び出しごとに別のSQLAlchemyUnitOfWorkを生成する. sessionは__aenter__まで作成しない.
        """
        return SQLAlchemyUnitOfWork(self._session_factory)


class SQLAlchemyUnitOfWork:
    """SQLAlchemy command repository群のtransaction境界を表す.

    Attributes:
        users (SQLAlchemyUserCommandRepository): user mutationを担当するrepository.
        roles (SQLAlchemyRoleCommandRepository): role mutationを担当するrepository.
        channels (SQLAlchemyChannelCommandRepository): channel mutationを担当するrepository.
        chat (SQLAlchemyChatCommandRepository): chat history mutationを担当するrepository.
        friends (SQLAlchemyFriendRelationshipCommandRepository):
            friend relationship mutationを担当するrepository.
        scores (SQLAlchemyScoreCommandRepository): score mutationを担当するrepository.
        personal_bests (SQLAlchemyPersonalBestCommandRepository):
            personal best mutationを担当するrepository.
        score_performance (SQLAlchemyScorePerformanceCommandRepository):
            performance calculation mutationを担当するrepository.
        submissions (SQLAlchemyScoreSubmissionCommandRepository):
            submission idempotency mutationを担当するrepository.
        replays (SQLAlchemyReplayCommandRepository):
            replay attachment mutationを担当するrepository.
        blobs (SQLAlchemyBlobCommandRepository): blob metadata mutationを担当するrepository.
        beatmaps (SQLAlchemyBeatmapCommandRepository):
            beatmap metadata mutationを担当するrepository.
        beatmap_leaderboards (SQLAlchemyBeatmapLeaderboardCommandRepository):
            leaderboard projection mutationを担当するrepository.
        beatmap_performance_bests (SQLAlchemyBeatmapPerformanceBestCommandRepository):
            beatmap performance best mutationを担当するrepository.
        current_user_stats (SQLAlchemyCurrentUserStatsCommandRepository):
            current user stats mutationを担当するrepository.
        _session_factory (SQLAlchemyCommandSessionFactory): scope開始時にsessionを生成するfactory.
        _session (AsyncSession | None): 現scopeへbindしたsession. enter前はNone.
        _committed (bool): commitが正常完了したかを示すflag.

    Notes:
        repository属性は__aenter__後だけ利用する.
        例外発生またはcommit未実行のscopeはexit時にrollbackする.
    """

    users: SQLAlchemyUserCommandRepository
    roles: SQLAlchemyRoleCommandRepository
    channels: SQLAlchemyChannelCommandRepository
    chat: SQLAlchemyChatCommandRepository
    friends: SQLAlchemyFriendRelationshipCommandRepository
    scores: SQLAlchemyScoreCommandRepository
    personal_bests: SQLAlchemyPersonalBestCommandRepository
    score_performance: SQLAlchemyScorePerformanceCommandRepository
    submissions: SQLAlchemyScoreSubmissionCommandRepository
    replays: SQLAlchemyReplayCommandRepository
    blobs: SQLAlchemyBlobCommandRepository
    beatmaps: SQLAlchemyBeatmapCommandRepository
    beatmap_leaderboards: SQLAlchemyBeatmapLeaderboardCommandRepository
    beatmap_performance_bests: SQLAlchemyBeatmapPerformanceBestCommandRepository
    current_user_stats: SQLAlchemyCurrentUserStatsCommandRepository

    def __init__(self, session_factory: SQLAlchemyCommandSessionFactory) -> None:
        """repository未bindのUnit of Workを初期化する.

        Args:
            session_factory (SQLAlchemyCommandSessionFactory): scope開始時に使うsession factory.

        """
        self._session_factory: SQLAlchemyCommandSessionFactory = session_factory
        self._session: AsyncSession | None = None
        self._committed: bool = False
        self.users = cast("SQLAlchemyUserCommandRepository", cast("object", None))
        self.roles = cast("SQLAlchemyRoleCommandRepository", cast("object", None))
        self.channels = cast("SQLAlchemyChannelCommandRepository", cast("object", None))
        self.chat = cast("SQLAlchemyChatCommandRepository", cast("object", None))
        self.friends = cast(
            "SQLAlchemyFriendRelationshipCommandRepository",
            cast("object", None),
        )
        self.scores = cast("SQLAlchemyScoreCommandRepository", cast("object", None))
        self.personal_bests = cast(
            "SQLAlchemyPersonalBestCommandRepository",
            cast("object", None),
        )
        self.score_performance = cast(
            "SQLAlchemyScorePerformanceCommandRepository",
            cast("object", None),
        )
        self.submissions = cast("SQLAlchemyScoreSubmissionCommandRepository", cast("object", None))
        self.replays = cast("SQLAlchemyReplayCommandRepository", cast("object", None))
        self.blobs = cast("SQLAlchemyBlobCommandRepository", cast("object", None))
        self.beatmaps = cast("SQLAlchemyBeatmapCommandRepository", cast("object", None))
        self.beatmap_leaderboards = cast(
            "SQLAlchemyBeatmapLeaderboardCommandRepository",
            cast("object", None),
        )
        self.beatmap_performance_bests = cast(
            "SQLAlchemyBeatmapPerformanceBestCommandRepository",
            cast("object", None),
        )
        self.current_user_stats = cast(
            "SQLAlchemyCurrentUserStatsCommandRepository",
            cast("object", None),
        )

    async def __aenter__(self) -> UnitOfWork:
        """sessionを生成して全command repositoryを同一transactionへbindする.

        Returns:
            UnitOfWork: command mutationとcommit/rollbackを実行できるentered scope.

        Notes:
            repositoryはこの時点で1つのAsyncSessionを共有する.
        """
        self._session = self._session_factory()
        self._bind_repositories(self._session)
        return cast("UnitOfWork", cast("object", self))

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        """scopeを終了し未commitまたは例外時のtransactionをrollbackしてsessionをcloseする.

        Args:
            exc_type (type[BaseException] | None): scope内exceptionの型. 正常終了時はNone.
            _exc (BaseException | None): scope内exceptionのinstance. 正常終了時はNone.
            _traceback (TracebackType | None): scope内exceptionのtraceback. 正常終了時はNone.

        Returns:
            None: 必要なrollbackとsession closeを完了し呼び出し側へ値を返さない.

        Raises:
            RuntimeError: __aenter__前に終了処理を呼び出してsessionが存在しない場合.

        Notes:
            例外があるscopeまたはcommit未実行のscopeはrollbackする.
            session closeはrollback失敗時も試みる.
        """
        session = self._require_session()
        try:
            if exc_type is not None or not self._committed:
                await session.rollback()
        finally:
            await session.close()

    async def commit(self) -> None:
        """現在のcommand transactionをcommit済みとして確定する.

        Returns:
            None: sessionをcommitしexit時の自動rollbackを抑止して値を返さない.

        Raises:
            RuntimeError: __aenter__前に呼び出されsessionが存在しない場合.
        """
        session = self._require_session()
        await session.commit()
        self._committed = True

    async def rollback(self) -> None:
        """現在のcommand transactionをrollbackしcommit済みflagを解除する.

        Returns:
            None: sessionをrollbackし値を返さずに完了する.

        Raises:
            RuntimeError: __aenter__前に呼び出されsessionが存在しない場合.
        """
        session = self._require_session()
        await session.rollback()
        self._committed = False

    def _bind_repositories(self, session: AsyncSession) -> None:
        """全command repositoryへ同一AsyncSessionをbindする.

        Args:
            session (AsyncSession): entered scopeが所有するtransaction用session.

        Returns:
            None: repository属性をsession-bound adapterで初期化し値を返さない.

        Notes:
            repository個別のcommit/rollbackは許可しない.
            transaction境界はこのUnit of Workが所有する.
        """
        self.users = SQLAlchemyUserCommandRepository(session)
        self.roles = SQLAlchemyRoleCommandRepository(session)
        self.channels = SQLAlchemyChannelCommandRepository(session)
        self.chat = SQLAlchemyChatCommandRepository(session)
        self.friends = SQLAlchemyFriendRelationshipCommandRepository(session)
        self.scores = SQLAlchemyScoreCommandRepository(session)
        self.personal_bests = SQLAlchemyPersonalBestCommandRepository(session)
        self.score_performance = SQLAlchemyScorePerformanceCommandRepository(session)
        self.submissions = SQLAlchemyScoreSubmissionCommandRepository(session)
        self.replays = SQLAlchemyReplayCommandRepository(session)
        self.blobs = SQLAlchemyBlobCommandRepository(session)
        self.beatmaps = SQLAlchemyBeatmapCommandRepository(session)
        self.beatmap_leaderboards = SQLAlchemyBeatmapLeaderboardCommandRepository(session)
        self.beatmap_performance_bests = SQLAlchemyBeatmapPerformanceBestCommandRepository(session)
        self.current_user_stats = SQLAlchemyCurrentUserStatsCommandRepository(session)

    def _require_session(self) -> AsyncSession:
        """Entered Unit of Workへbind済みのAsyncSessionを返す.

        Returns:
            AsyncSession: 現scopeのrepositoryが共有するsession.

        Raises:
            RuntimeError: __aenter__前にtransaction操作または終了処理を呼び出した場合.
        """
        if self._session is None:
            msg = "SQLAlchemyUnitOfWork must be entered before use"
            raise RuntimeError(msg)
        return self._session
