"""In-memory replay download query repository."""

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
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryReplayDownloadQueryRepository:
    """Replay download candidate を committed memory state から投影する.

    Args:
        uow_factory: Committed in-memory state snapshot を返す Unit of Work factory.

    Returns:
        Class のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Raw replay bytes, blob storage key, filesystem path は読まない.
        Score, owner visibility, replay attachment metadata だけを参照する.
    """

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Repository を committed state snapshot factory で初期化する.

        Args:
            uow_factory: Query ごとに committed state snapshot を生成する factory.

        Returns:
            None.

        Raises:
            なし.

        Constraints:
            Factory は保持するだけで snapshot は query 実行時に取得する.
        """
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def get_candidate(
        self,
        query: ReplayDownloadCandidateQuery,
    ) -> ReplayDownloadCandidate:
        """Score id と ruleset から replay download candidate branch を返す.

        Args:
            query: Parsed score id と Stable ruleset scope.

        Returns:
            Score not found, hidden score, missing replay, available replay のいずれか.

        Raises:
            なし.

        Constraints:
            Committed memory state の metadata だけを投影する. Blob object の
            storage key や raw bytes は読まない.
        """
        state = self._factory.snapshot()
        score = state.scores_by_id.get(query.score_id)
        if score is None or score.id != query.score_id or score.ruleset is not query.ruleset:
            return ReplayDownloadScoreNotFoundCandidate()

        if not _score_is_replay_download_visible(state, score):
            return ReplayDownloadHiddenScoreCandidate()

        replay = _replay_for_score(state, query.score_id)
        if replay is None:
            return ReplayDownloadMissingReplayCandidate()

        return ReplayDownloadAvailableReplayCandidate(
            blob_id=replay.blob_id,
            checksum=replay.checksum_sha256,
            byte_size=replay.byte_size,
        )


def _score_is_replay_download_visible(
    state: InMemoryCommandRepositoryState,
    score: Score,
) -> bool:
    score_id = score.id
    if score_id is None:
        return False
    return (
        score.passed
        and state.score_leaderboard_eligibility_by_id.get(score_id, False)
        and _user_is_visible(state, score.user_id)
    )


def _user_is_visible(state: InMemoryCommandRepositoryState, user_id: int) -> bool:
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
    return next(
        (replay for replay in state.replays_by_id.values() if replay.score_id == score_id),
        None,
    )


__all__ = ["InMemoryReplayDownloadQueryRepository"]
