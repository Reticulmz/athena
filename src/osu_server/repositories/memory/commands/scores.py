"""In-memory command 側 score repository を実装する module."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.domain.scores.mods import Mod
from osu_server.repositories.interfaces.commands.beatmaps import BeatmapSubmissionCounts

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.scores.score import Playstyle, Ruleset, Score
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryScoreCommandRepository:
    """Score primary record, checksum index, leaderboard query candidates を管理する.

    Attributes:
        _state (InMemoryCommandRepositoryState): 所有 Unit of Work の可変 state snapshot.

    Notes:
        この repository は lock 又は thread synchronization を提供しない. 同じ state を
        複数 task 又は thread から同時に変更してはならない.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """Active Unit of Work の state snapshot を保持する.

        Args:
            state (InMemoryCommandRepositoryState): repository が直接読み書きする state.

        Returns:
            None: state への参照を保持したことを示す.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def create(self, score: Score) -> Score:
        """一意な online checksum を持つ score を作成し ID を割り当てる.

        Args:
            score (Score): 保存する score. 入力 ID は保存時に置き換える.

        Returns:
            Score: next_score_id を割り当てて保存した score.

        Raises:
            ValueError: score.online_checksum が checksum index にすでに存在する場合.

        Notes:
            成功時は next_score_id, 主記録, checksum index, submission 時点の leaderboard
            eligibility snapshot を更新する.
        """
        if score.online_checksum in self._state.score_id_by_online_checksum:
            msg = f"online_checksum already exists: {score.online_checksum}"
            raise ValueError(msg)

        created = replace(score, id=self._state.next_score_id)
        assert created.id is not None
        self._state.next_score_id += 1
        self._state.scores_by_id[created.id] = created
        self._state.score_id_by_online_checksum[created.online_checksum] = created.id
        self._state.score_leaderboard_eligibility_by_id[created.id] = (
            created.leaderboard_eligible_at_submission
        )
        return created

    async def exists_by_online_checksum(self, checksum: str) -> bool:
        """Online checksum が checksum index に存在するか返す.

        Args:
            checksum (str): 存在確認する online checksum.

        Returns:
            bool: checksum index に key が存在する場合は True.
        """
        return checksum in self._state.score_id_by_online_checksum

    async def get_by_online_checksum(self, checksum: str) -> Score | None:
        """Online checksum から保存済み score を返す.

        Args:
            checksum (str): 検索する online checksum.

        Returns:
            Score | None: index と主記録が存在する score. 未登録又は不整合時は None.
        """
        score_id = self._state.score_id_by_online_checksum.get(checksum)
        if score_id is None:
            return None
        return self._state.scores_by_id.get(score_id)

    async def get_by_id(self, score_id: int) -> Score | None:
        """Score ID から保存済み score を返す.

        Args:
            score_id (int): 検索する score の識別子.

        Returns:
            Score | None: 保存済み score. 未登録なら None.
        """
        return self._state.scores_by_id.get(score_id)

    async def increment_replay_view_count(self, score_id: int) -> bool:
        """対象 score の replay view count を 1 増やす.

        Args:
            score_id (int): replay view を加算する score の識別子.

        Returns:
            bool: score を更新した場合は True. 未登録なら False.

        Notes:
            未登録 score の場合は state を変更しない.
        """
        existing = self._state.scores_by_id.get(score_id)
        if existing is None:
            return False
        self._state.scores_by_id[score_id] = replace(
            existing,
            replay_view_count=existing.replay_view_count + 1,
        )
        return True

    async def count_submissions_for_beatmap(self, beatmap_id: int) -> BeatmapSubmissionCounts:
        """主記録の score から beatmap の play count と pass count を集計する.

        Args:
            beatmap_id (int): 集計する beatmap の識別子.

        Returns:
            BeatmapSubmissionCounts: score 数を play_count, passed score 数を pass_count とする
                集計値.

        Notes:
            state を変更しない. beatmap 主記録の存在は検証しない.
        """
        scores = tuple(
            score for score in self._state.scores_by_id.values() if score.beatmap_id == beatmap_id
        )
        return BeatmapSubmissionCounts(
            play_count=len(scores),
            pass_count=sum(1 for score in scores if score.passed),
        )

    async def list_current_stats_scores_for_user(
        self,
        user_id: int,
        *,
        ruleset: Ruleset,
        playstyle: Playstyle,
    ) -> tuple[Score, ...]:
        """Current UserStats に寄与する user の scores を安定順で返す.

        Args:
            user_id (int): score を検索する user の識別子.
            ruleset (Ruleset): 検索する ruleset.
            playstyle (Playstyle): 検索する playstyle.

        Returns:
            tuple[Score, ...]: Relax と Autopilot を除いた scores の submitted_at, ID 昇順 tuple.
        """
        return tuple(
            sorted(
                (
                    score
                    for score in self._state.scores_by_id.values()
                    if score.user_id == user_id
                    and _is_current_stats_score(
                        score,
                        ruleset=ruleset,
                        playstyle=playstyle,
                    )
                ),
                key=lambda score: (score.submitted_at, score.id or 0),
            )
        )

    async def list_leaderboard_rebuild_candidates_for_user(
        self,
        user_id: int,
    ) -> tuple[Score, ...]:
        """一人の user に属する leaderboard rebuild candidate scores を返す.

        Args:
            user_id (int): candidate を検索する user の識別子.

        Returns:
            tuple[Score, ...]: eligibility 条件を満たす scores の rebuild sort key 昇順 tuple.

        Notes:
            passed で submission 時 eligibility があり, ID と対応 beatmap が存在し, beatmap
            checksum が current beatmap checksum と一致する score だけを返す.
        """
        return tuple(
            sorted(
                (
                    score
                    for score in self._state.scores_by_id.values()
                    if score.user_id == user_id
                    and _is_leaderboard_rebuild_candidate(score, self._state)
                ),
                key=_rebuild_candidate_sort_key,
            )
        )

    async def list_leaderboard_rebuild_candidates_for_beatmap_ids(
        self,
        beatmap_ids: tuple[int, ...],
    ) -> tuple[Score, ...]:
        """指定 beatmap IDs に属する leaderboard rebuild candidate scores を返す.

        Args:
            beatmap_ids (tuple[int, ...]): candidate を検索する beatmap IDs. 重複は無視する.

        Returns:
            tuple[Score, ...]: eligibility 条件を満たす scores の rebuild sort key 昇順 tuple.

        Notes:
            beatmap_ids が空なら空 tuple を返す. candidate の条件は user 検索と同じである.
        """
        beatmap_id_set = frozenset(beatmap_ids)
        if len(beatmap_id_set) == 0:
            return ()
        return tuple(
            sorted(
                (
                    score
                    for score in self._state.scores_by_id.values()
                    if score.beatmap_id in beatmap_id_set
                    and _is_leaderboard_rebuild_candidate(score, self._state)
                ),
                key=_rebuild_candidate_sort_key,
            )
        )


def _is_leaderboard_rebuild_candidate(
    score: Score,
    state: InMemoryCommandRepositoryState,
) -> bool:
    """Score が leaderboard rebuild の対象条件を満たすか判定する.

    Args:
        score (Score): 判定する保存済み score.
        state (InMemoryCommandRepositoryState): score の current beatmap を参照する state snapshot.

    Returns:
        bool: passed, submission eligibility, non-None ID, current beatmap の存在, checksum 一致を
        すべて満たす場合は True.
    """
    beatmap = state.beatmaps_by_id.get(score.beatmap_id)
    return (
        score.passed
        and score.leaderboard_eligible_at_submission
        and score.id is not None
        and beatmap is not None
        and score.beatmap_checksum == beatmap.checksum_md5
    )


def _is_current_stats_score(
    score: Score,
    *,
    ruleset: Ruleset,
    playstyle: Playstyle,
) -> bool:
    """Score が current UserStats 集計の対象条件を満たすか判定する.

    Args:
        score (Score): 判定する score.
        ruleset (Ruleset): 必須の ruleset.
        playstyle (Playstyle): 必須の playstyle.

    Returns:
        bool: mode が一致し, Relax と Autopilot mod のどちらも含まない場合は True.
    """
    return (
        score.ruleset is ruleset
        and score.playstyle is playstyle
        and not score.mods.has(Mod.RELAX)
        and not score.mods.has(Mod.AUTOPILOT)
    )


def _rebuild_candidate_sort_key(score: Score) -> tuple[int, int, int, int, int, datetime, int]:
    """Leaderboard rebuild candidate を deterministic に整列する key を返す.

    Args:
        score (Score): sort key を作る candidate score.

    Returns:
        tuple[int, int, int, int, int, datetime, int]: beatmap ID, ruleset value, playstyle value,
        user ID, score 降順値, submitted_at, score ID の順の key.

    Raises:
        AssertionError: score.id が None の場合.
    """
    assert score.id is not None
    return (
        score.beatmap_id,
        score.ruleset.value,
        score.playstyle.value,
        score.user_id,
        -score.score,
        score.submitted_at,
        score.id,
    )
