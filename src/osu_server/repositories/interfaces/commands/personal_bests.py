"""Personal best projection の command-side repository 契約."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.personal_best import PersonalBest, PersonalBestScope


@dataclass(frozen=True, slots=True)
class UpsertPersonalBest:
    """候補が優位な場合に personal best projection を作成または置換する command.

    Attributes:
        scope (PersonalBestScope): Personal best を比較する自然キー.
        score_id (int): 候補 score の正の識別子.
        ranking_value (int): 優劣比較に使う非負の値.
    """

    scope: PersonalBestScope
    score_id: int
    ranking_value: int

    def __post_init__(self) -> None:
        """Upsert 候補の識別子とランキング値を検証する.

        Returns:
            None: score_id と ranking_value が候補の制約を満たすことを示す.

        Raises:
            ValueError: score_id が正でない場合,または ranking_value が負の場合に送出する.
        """
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)
        if self.ranking_value < 0:
            msg = "ranking_value must not be negative"
            raise ValueError(msg)


class PersonalBestCommandRepository(Protocol):
    """Personal best projection の mutation と consistency-check port.

    Notes:
        Runtime 実装は command Unit of Work から取得する.各操作は同じ Unit of Work が
        所有する transaction に参加し,この repository 自身は commit または rollback を
        実行しない.
    """

    async def get_by_scope(self, scope: PersonalBestScope) -> PersonalBest | None:
        """1 scope の現在の personal best を返す.

        Args:
            scope (PersonalBestScope): 取得する personal best の自然キー.

        Returns:
            PersonalBest | None: 現在の personal best.未登録時は None.
        """
        ...

    async def upsert_if_better(self, command: UpsertPersonalBest) -> PersonalBest:
        """候補が現在の personal best より優位な場合に永続化する.

        Args:
            command (UpsertPersonalBest): 比較して保存する候補.

        Returns:
            PersonalBest: Upsert 後に scope を代表する personal best.
        """
        ...
