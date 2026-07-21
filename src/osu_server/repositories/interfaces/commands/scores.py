"""Score ingestion の command-side repository 契約."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Playstyle, Ruleset, Score
    from osu_server.repositories.interfaces.commands.beatmaps import BeatmapSubmissionCounts


@runtime_checkable
class ScoreCommandRepository(Protocol):
    """Score ingestion の mutation と consistency-check port.

    Notes:
        Runtime 実装は command Unit of Work から取得する。各操作は同じ Unit of Work が
        所有する transaction に参加し、この repository 自身は commit または rollback を
        実行しない.
    """

    async def create(self, score: Score) -> Score:
        """Score を永続化し repository-assigned identity 付きで返す.

        Args:
            score (Score): 永続化する未保存 Score.

        Returns:
            Score: Repository-assigned identity を含む永続化後の Score.

        Raises:
            ValueError: online checksum が既存 Score と重複する場合に送出する.
        """
        ...

    async def exists_by_online_checksum(self, checksum: str) -> bool:
        """Score checksum が既に存在するか返す.

        Args:
            checksum (str): 重複確認する online score checksum.

        Returns:
            bool: 一致する Score が存在する場合は True。存在しない場合は False.
        """
        ...

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        """Idempotency check 用に checksum から Score を返す.

        Args:
            checksum (str): 検索する online score checksum.

        Returns:
            Score | None: 一致する Score。存在しない場合は None.
        """
        ...

    async def get_by_id(self, score_id: int) -> Score | None:
        """Command-side consistency check 用に identifier から Score を返す.

        Args:
            score_id (int): 取得する Score ID.

        Returns:
            Score | None: 一致する Score。存在しない場合は None.
        """
        ...

    async def increment_replay_view_count(self, score_id: int) -> bool:
        """対象 score の Replay View Count を 1 増やし、存在したか返す.

        Args:
            score_id (int): Replay View Count を増やす対象 score の identifier.

        Returns:
            bool: 対象 score が存在し、increment を実行した場合は True。存在しない
                場合は False.
        """
        ...

    async def count_submissions_for_beatmap(self, beatmap_id: int) -> BeatmapSubmissionCounts:
        """1 Beatmap の累積 submitted play/pass count を返す.

        Args:
            beatmap_id (int): Count を集計する Beatmap ID.

        Returns:
            BeatmapSubmissionCounts: Beatmap の累積 submitted play/pass count.
        """
        ...

    async def list_current_stats_scores_for_user(
        self,
        user_id: int,
        *,
        ruleset: Ruleset,
        playstyle: Playstyle,
    ) -> tuple[Score, ...]:
        """1 user の current UserStats projection 再構築に使う source Score を返す.

        Args:
            user_id (int): Source Score を取得する User ID.
            ruleset (Ruleset): 絞り込む ruleset.
            playstyle (Playstyle): 絞り込む playstyle.

        Returns:
            tuple[Score, ...]: Projection 再構築対象となる source Score 群.
        """
        ...

    async def list_leaderboard_rebuild_candidates_for_user(
        self,
        user_id: int,
    ) -> tuple[Score, ...]:
        """1 user の leaderboard slice 再構築対象となる eligible Score を返す.

        Args:
            user_id (int): Source Score を取得する User ID.

        Returns:
            tuple[Score, ...]: User の leaderboard slice 再構築対象 Score 群.
        """
        ...

    async def list_leaderboard_rebuild_candidates_for_beatmap_ids(
        self,
        beatmap_ids: tuple[int, ...],
    ) -> tuple[Score, ...]:
        """1 Beatmap projection slice 再構築対象となる eligible Score を返す.

        Args:
            beatmap_ids (tuple[int, ...]): Source Score を取得する Beatmap ID 群.

        Returns:
            tuple[Score, ...]: Beatmap projection slice 再構築対象 Score 群.
        """
        ...
