"""Display と compatibility workflow 用 score read-only repository contract を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Score


class ScoreQueryRepository(Protocol):
    """Display と compatibility workflow 用 score read-only access を定義する.

    Notes:
        この Protocol は Score read model を返すだけである. Score を作成または更新せず Command
        Unit of Work を開始または commit/rollback しない.
    """

    async def get_by_id(self, score_id: int) -> Score | None:
        """Identifier に対応する Score を返す.

        Args:
            score_id (int): 検索する Score ID.

        Returns:
            Score | None: 対応する Score. 見つからない場合は `None`.
        """
        ...

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        """Online checksum に対応する Score を返す.

        Args:
            checksum (str): 検索する online checksum.

        Returns:
            Score | None: 対応する Score. 見つからない場合は `None`.
        """
        ...
