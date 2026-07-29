"""Committed in-memory state から replay download candidate を投影する adapter を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.leaderboard_visibility import is_leaderboard_visible_user
from osu_server.repositories.interfaces.queries.replay_download import (
    ReplayDownloadAvailableReplayCandidate,
    ReplayDownloadCandidate,
    ReplayDownloadCandidateQuery,
    ReplayDownloadHiddenScoreCandidate,
    ReplayDownloadMissingReplayCandidate,
    ReplayDownloadScoreNotFoundCandidate,
)

if TYPE_CHECKING:
    from osu_server.domain.scores.replay import Replay
    from osu_server.domain.scores.score import Score
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
    from osu_server.repositories.memory.queries.state import InMemoryQueryStateSnapshotProvider


class InMemoryReplayDownloadQueryRepository:
    """Committed in-memory state から replay download candidate を投影する.

    Attributes:
        _snapshot_provider (InMemoryQueryStateSnapshotProvider): query ごとの committed state
            snapshot provider.

    Notes:
        Raw replay bytes, Blob storage key, filesystem path は読まない. Score, owner visibility,
        Replay attachment metadata だけを参照し, state を変更しない.
    """

    def __init__(self, snapshot_provider: InMemoryQueryStateSnapshotProvider) -> None:
        """Query-side snapshot provider を保持する.

        Args:
            snapshot_provider (InMemoryQueryStateSnapshotProvider): query ごとに committed state の
                clone を返す provider.

        Notes:
            Command Unit of Work factory には依存せず, snapshot は各 query 実行時に取得する.
        """
        self._snapshot_provider: InMemoryQueryStateSnapshotProvider = snapshot_provider

    async def get_candidate(
        self,
        query: ReplayDownloadCandidateQuery,
    ) -> ReplayDownloadCandidate:
        """Score ID と ruleset に対応する replay download branch を返す.

        Args:
            query (ReplayDownloadCandidateQuery): parsed Score ID と Stable ruleset scope.

        Returns:
            ReplayDownloadCandidate: Score not found, hidden score, missing replay,
            available replay のいずれかの candidate.

        Notes:
            committed state の metadata だけを投影する. Blob object の storage key や raw bytes は
            読まず, state を変更しない.
        """
        state = self._snapshot_provider.snapshot()
        score = state.scores_by_id.get(query.score_id)
        score_id = score.id if score is not None else None
        if (
            score is None
            or score_id is None
            or score_id != query.score_id
            or score.ruleset is not query.ruleset
        ):
            return ReplayDownloadScoreNotFoundCandidate()

        if not _score_is_replay_download_visible(state, score):
            return ReplayDownloadHiddenScoreCandidate()

        replay = _replay_for_score(state, query.score_id)
        if replay is None:
            return ReplayDownloadMissingReplayCandidate()

        return ReplayDownloadAvailableReplayCandidate(
            score_id=score_id,
            score_owner_user_id=score.user_id,
            blob_id=replay.blob_id,
            checksum=replay.checksum_sha256,
            byte_size=replay.byte_size,
        )


def _score_is_replay_download_visible(
    state: InMemoryCommandRepositoryState,
    score: Score,
) -> bool:
    """Score が replay download に公開可能かを判定する.

    Args:
        state (InMemoryCommandRepositoryState): Score eligibility と Role assignment を含む
            snapshot.
        score (Score): 判定する Score.

    Returns:
        bool: ID を持ち, passed で, leaderboard eligible かつ owner が可視なら True.

    Notes:
        state と score は変更しない.
    """
    score_id = score.id
    if score_id is None:
        return False
    return (
        score.passed
        and state.score_leaderboard_eligibility_by_id.get(score_id, False)
        and _user_is_visible(state, score.user_id)
    )


def _user_is_visible(state: InMemoryCommandRepositoryState, user_id: int) -> bool:
    """User に割り当てられた Role permissions から leaderboard 可視性を判定する.

    Args:
        state (InMemoryCommandRepositoryState): Role と User Role assignment を含む snapshot.
        user_id (int): 可視性を判定する User の ID.

    Returns:
        bool: 合成した Privileges が leaderboard-visible なら True, それ以外は False.

    Notes:
        存在しない Role ID は無視し, state を変更しない.
    """
    privileges = Privileges.NONE
    for role_id in state.role_ids_by_user_id.get(user_id, set()):
        role = state.roles_by_id.get(role_id)
        if role is not None:
            privileges |= role.permissions
    return is_leaderboard_visible_user(privileges)


def _replay_for_score(
    state: InMemoryCommandRepositoryState,
    score_id: int,
) -> Replay | None:
    """Score ID に対応する最初の Replay を取得する.

    Args:
        state (InMemoryCommandRepositoryState): Replay record を含む snapshot.
        score_id (int): 対応する Replay を検索する Score の ID.

    Returns:
        Replay | None: replays_by_id の反復順で最初に一致した Replay. 一致しなければ None.

    Notes:
        state を変更しない.
    """
    return next(
        (replay for replay in state.replays_by_id.values() if replay.score_id == score_id),
        None,
    )


__all__ = ["InMemoryReplayDownloadQueryRepository"]
