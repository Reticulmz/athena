"""Score replay persistence の command-side repository 契約."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.replay import Replay


class ReplayCommandRepository(Protocol):
    """Score replay の mutation と uniqueness-check port.

    Notes:
        Runtime 実装は command Unit of Work から取得する.各操作は同じ Unit of Work が
        所有する transaction に参加し,この repository 自身は commit または rollback を
        実行しない.
    """

    async def create(self, replay: Replay) -> Replay:
        """Replay を永続化し repository-assigned identity 付きで返す.

        Args:
            replay (Replay): 永続化する未保存 Replay.

        Returns:
            Replay: Repository-assigned identity を含む永続化後の Replay.

        Raises:
            ValueError: checksum_sha256 が既存 Replay と重複する場合に送出する.
        """
        ...

    async def exists_by_checksum(self, checksum: str) -> bool:
        """Checksum を持つ Replay が既に存在するか返す.

        Args:
            checksum (str): 重複確認する Replay checksum.

        Returns:
            bool: 一致する Replay が存在する場合は True.存在しない場合は False.
        """
        ...
