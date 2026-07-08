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
    from osu_server.repositories.memory.queries.state import InMemoryQueryStateSnapshotProvider


class InMemoryReplayDownloadQueryRepository:
    """Replay download candidate を committed memory state から投影する.

    引数:
        snapshot_provider: Committed in-memory state snapshot を返す query-side provider.

    戻り値:
        Class のため戻り値はない.

    例外:
        なし.

    制約:
        Raw replay bytes, blob storage key, filesystem path は読まない.
        Score, owner visibility, replay attachment metadata だけを参照する.
    """

    def __init__(self, snapshot_provider: InMemoryQueryStateSnapshotProvider) -> None:
        """Repository を query-side snapshot provider で初期化する.

        引数:
            snapshot_provider: Query ごとに committed state snapshot を生成する provider.

        戻り値:
            None.

        例外:
            なし.

        制約:
            Command Unit of Work factory ではなく query-side provider だけに依存する.
            Snapshot は query 実行時に取得する.
        """
        self._snapshot_provider: InMemoryQueryStateSnapshotProvider = snapshot_provider

    async def get_candidate(
        self,
        query: ReplayDownloadCandidateQuery,
    ) -> ReplayDownloadCandidate:
        """Score id と ruleset から replay download candidate branch を返す.

        引数:
            query: Parsed score id と Stable ruleset scope.

        戻り値:
            Score not found, hidden score, missing replay, available replay のいずれか.

        例外:
            なし.

        制約:
            Committed memory state の metadata だけを投影する. Blob object の
            storage key や raw bytes は読まない.
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
