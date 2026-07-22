"""Committed in-memory state から Score を読む query adapter を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Score
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryScoreQueryRepository:
    """Committed in-memory state を読む read-only Score repository.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): query ごとの committed snapshot を生成する factory.

    Notes:
        各 query は snapshot だけを読み, Score state を変更しない.
    """

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Committed snapshot を取得する factory を保持する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): read に使用する committed state factory.

        Returns:
            None: factory を保持する repository を構築する.
        """
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def get_by_id(self, score_id: int) -> Score | None:
        """ID で Score を取得する.

        Args:
            score_id (int): 取得する Score の ID.

        Returns:
            Score | None: snapshot 内の Score. ID がなければ None.
        """
        state = self._factory.snapshot()
        return state.scores_by_id.get(score_id)

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        """Online checksum の索引から Score を取得する.

        Args:
            checksum (str): 検索する Score の online checksum.

        Returns:
            Score | None: 索引先の Score. checksum または Score がなければ None.
        """
        state = self._factory.snapshot()
        score_id = state.score_id_by_online_checksum.get(checksum)
        if score_id is None:
            return None
        return state.scores_by_id.get(score_id)
