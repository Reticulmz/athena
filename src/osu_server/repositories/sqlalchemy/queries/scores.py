"""SQLAlchemyからScoreをread-onlyで取得するquery repositoryを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from osu_server.repositories.sqlalchemy.models.score import ScoreModel
from osu_server.repositories.sqlalchemy.queries._shared import (
    SQLAlchemyQuerySessionFactory,
    score_to_domain,
)

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Score


class SQLAlchemyScoreQueryRepository:
    """短命なSQLAlchemy read sessionでScoreを取得する.

    Attributes:
        _session_factory (SQLAlchemyQuerySessionFactory): queryごとに閉じるread sessionのfactory.
    """

    _session_factory: SQLAlchemyQuerySessionFactory

    def __init__(self, session_factory: SQLAlchemyQuerySessionFactory) -> None:
        """読み取り用session factoryを保持してrepositoryを初期化する.

        Args:
            session_factory (SQLAlchemyQuerySessionFactory): query用の非同期read session factory.

        Returns:
            None: 読み取り用session factoryを保持したrepository instanceを初期化する.

        Notes:
            初期化時にはsessionを生成せず,各read operationで短命なsessionを開閉する.
        """
        self._session_factory = session_factory

    async def get_by_id(self, score_id: int) -> Score | None:
        """Score IDに一致するdomain Scoreを取得する.

        Args:
            score_id (int): 取得対象Scoreの永続ID.

        Returns:
            Score | None: domain Score. 対象rowが存在しない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: modelのenum値またはmods bitmaskをdomain Scoreへ変換できない場合.

        Notes:
            Scoreおよび関連する永続stateは変更しない.
        """
        async with self._session_factory() as session:
            model = await session.get(ScoreModel, score_id)
            return score_to_domain(model) if isinstance(model, ScoreModel) else None

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        """Online checksumに一致するdomain Scoreを取得する.

        Args:
            checksum (str): 完全一致で検索するonline checksum.

        Returns:
            Score | None: domain Score. 対象rowが存在しない場合はNone.

        Raises:
            SQLAlchemyError: sessionのreadまたはrow取得に失敗した場合.
            ValueError: modelのenum値またはmods bitmaskをdomain Scoreへ変換できない場合.

        Notes:
            checksumの正規化は行わないため,呼び出し側はsubmission時の値を渡す.
        """
        async with self._session_factory() as session:
            model = (
                await session.execute(
                    select(ScoreModel).where(ScoreModel.online_checksum == checksum)
                )
            ).scalar_one_or_none()
            return score_to_domain(model) if isinstance(model, ScoreModel) else None
