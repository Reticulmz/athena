"""SQLAlchemyでscore replay metadataを永続化するrepositoryを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from osu_server.domain.scores.replay import Replay
from osu_server.repositories.sqlalchemy.models.score import ReplayModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SQLAlchemyReplayCommandRepository:
    """Unit of Work所有sessionでscore replay metadataを操作するrepository.

    Attributes:
        _session (AsyncSession): command transactionを実行しcommitを所有しないsession.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Workから受け取ったSQLAlchemy sessionを保持する.

        Args:
            session (AsyncSession): replay metadata操作に使うsession.

        Returns:
            None: repositoryの初期化完了を示す.

        Notes:
            commitとrollbackは呼び出し側のUnit of Workが所有する.
        """
        self._session: AsyncSession = session

    async def create(self, replay: Replay) -> Replay:
        """新しいreplay metadataを永続化してdomain modelへ変換する.

        Args:
            replay (Replay): scoreとblobとSHA-256 checksumを持つ新規replay metadata.

        Returns:
            Replay: flushとrefresh後の永続化済みreplay metadata.

        Raises:
            ValueError: 同じchecksum_sha256のreplayが既に存在する場合.
            SQLAlchemyError: checksum重複以外の永続化処理に失敗した場合.

        Notes:
            このmethodはUnit of Workをcommitしない.
        """
        model = ReplayModel(
            score_id=replay.score_id,
            blob_id=replay.blob_id,
            checksum_sha256=replay.checksum_sha256,
            byte_size=replay.byte_size,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "checksum_sha256" in str(exc):
                msg = f"checksum_sha256 already exists: {replay.checksum_sha256}"
                raise ValueError(msg) from exc
            raise
        await self._session.refresh(model)
        return _replay_to_domain(model)

    async def exists_by_checksum(self, checksum: str) -> bool:
        """SHA-256 checksumを持つreplay metadataが存在するか確認する.

        Args:
            checksum (str): 確認対象replayのSHA-256 checksum.

        Returns:
            bool: 対応するreplayが存在する場合はTrue. 存在しない場合はFalse.

        Raises:
            SQLAlchemyError: select実行に失敗した場合.
        """
        result = (
            await self._session.execute(
                select(ReplayModel.id).where(ReplayModel.checksum_sha256 == checksum)
            )
        ).scalar_one_or_none()
        return result is not None


def _replay_to_domain(model: ReplayModel) -> Replay:
    """SQLAlchemy replay modelをscore domain modelへ変換する.

    Args:
        model (ReplayModel): 永続化層から読み出したreplay row.

    Returns:
        Replay: scoreとblobへの参照を維持したreplay metadata.
    """
    return Replay(
        id=model.id,
        score_id=model.score_id,
        blob_id=model.blob_id,
        checksum_sha256=model.checksum_sha256,
        byte_size=model.byte_size,
    )
