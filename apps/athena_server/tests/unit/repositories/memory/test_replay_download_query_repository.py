"""メモリ上のリプレイ取得候補クエリを検証する."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.replay import Replay
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.queries.replay_download import (
    ReplayDownloadAvailableReplayCandidate,
    ReplayDownloadCandidateKind,
    ReplayDownloadCandidateQuery,
    ReplayDownloadHiddenScoreCandidate,
    ReplayDownloadMissingReplayCandidate,
    ReplayDownloadScoreNotFoundCandidate,
)
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.replay_download import (
    InMemoryReplayDownloadQueryRepository,
)
from osu_server.repositories.memory.queries.state import InMemoryQueryStateSnapshotProvider
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

_NOW = datetime(2026, 6, 18, tzinfo=UTC)
_VISIBLE_ROLE_ID = 1


async def test_get_candidate_returns_score_not_found_for_missing_id_and_ruleset_mismatch() -> None:
    """存在しないIDとルールセット不一致が未検出候補になることを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory, state, repository = _make_repository_context()
    _seed_visible_role(state, user_id=100)
    _seed_score(state, score_id=10, user_id=100, ruleset=Ruleset.TAIKO)
    factory.commit_state(state)

    missing = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=999, ruleset=Ruleset.OSU)
    )
    ruleset_mismatch = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=10, ruleset=Ruleset.OSU)
    )

    assert isinstance(missing, ReplayDownloadScoreNotFoundCandidate)
    assert missing.kind is ReplayDownloadCandidateKind.SCORE_NOT_FOUND
    assert isinstance(ruleset_mismatch, ReplayDownloadScoreNotFoundCandidate)
    assert ruleset_mismatch.kind is ReplayDownloadCandidateKind.SCORE_NOT_FOUND


@pytest.mark.parametrize(
    ("passed", "leaderboard_eligible", "assign_visible_role"),
    [
        (False, True, True),
        (True, False, True),
        (True, True, False),
    ],
)
async def test_get_candidate_returns_hidden_when_visibility_inputs_are_false(
    *,
    passed: bool,
    leaderboard_eligible: bool,
    assign_visible_role: bool,
) -> None:
    """可視性条件のいずれかが偽なら非公開候補になることを検証する.

    Args:
        passed (bool): スコアが合格済みかどうか.
        leaderboard_eligible (bool): スコアがリーダーボード対象かどうか.
        assign_visible_role (bool): 所有者へ可視ロールを割り当てるかどうか.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory, state, repository = _make_repository_context()
    if assign_visible_role:
        _seed_visible_role(state, user_id=100)
    _seed_score(
        state,
        score_id=20,
        user_id=100,
        passed=passed,
        leaderboard_eligible=leaderboard_eligible,
    )
    _seed_replay(state, score_id=20)
    factory.commit_state(state)

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=20, ruleset=Ruleset.OSU)
    )

    assert isinstance(result, ReplayDownloadHiddenScoreCandidate)
    assert result.kind is ReplayDownloadCandidateKind.HIDDEN_SCORE


async def test_get_candidate_returns_missing_replay_for_visible_score_without_attachment() -> None:
    """可視スコアに添付リプレイがない場合の欠落候補を検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory, state, repository = _make_repository_context()
    _seed_visible_role(state, user_id=100)
    _seed_score(state, score_id=30, user_id=100)
    factory.commit_state(state)

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=30, ruleset=Ruleset.OSU)
    )

    assert isinstance(result, ReplayDownloadMissingReplayCandidate)
    assert result.kind is ReplayDownloadCandidateKind.MISSING_REPLAY


async def test_get_candidate_maps_available_replay_metadata_without_blob_state() -> None:
    """添付済みリプレイのメタデータだけを利用可能候補へ写像することを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    factory, state, repository = _make_repository_context()
    _seed_visible_role(state, user_id=100)
    _seed_score(state, score_id=40, user_id=100)
    _seed_replay(
        state,
        score_id=40,
        blob_id=456,
        checksum="c" * 64,
        byte_size=8192,
    )
    factory.commit_state(state)

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=40, ruleset=Ruleset.OSU)
    )

    assert result == ReplayDownloadAvailableReplayCandidate(
        score_id=40,
        score_owner_user_id=100,
        blob_id=456,
        checksum="c" * 64,
        byte_size=8192,
    )
    assert result.kind is ReplayDownloadCandidateKind.AVAILABLE_REPLAY


async def test_get_candidate_reads_only_committed_memory_state() -> None:
    """未コミットの作業状態をクエリが参照しないことを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    _, pending_state, repository = _make_repository_context()
    _seed_visible_role(pending_state, user_id=100)
    _seed_score(pending_state, score_id=50, user_id=100)
    _seed_replay(pending_state, score_id=50)

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=50, ruleset=Ruleset.OSU)
    )

    assert isinstance(result, ReplayDownloadScoreNotFoundCandidate)
    assert result.kind is ReplayDownloadCandidateKind.SCORE_NOT_FOUND


def _make_repository_context() -> tuple[
    InMemoryUnitOfWorkFactory,
    InMemoryCommandRepositoryState,
    InMemoryReplayDownloadQueryRepository,
]:
    """独立したリプレイ候補クエリ用の作業状態とrepositoryを生成する.

    Returns:
        tuple: Unit of Work factoryと作業用状態と候補クエリrepositoryの組.
    """
    committed_state = InMemoryCommandRepositoryState()
    factory = InMemoryUnitOfWorkFactory(committed_state)
    repository = InMemoryReplayDownloadQueryRepository(
        InMemoryQueryStateSnapshotProvider(committed_state)
    )
    return factory, factory.snapshot(), repository


def _seed_visible_role(state: InMemoryCommandRepositoryState, *, user_id: int) -> None:
    """指定ユーザーを可視スコアの所有者として状態へ登録する.

    Args:
        state (InMemoryCommandRepositoryState): 変更対象のメモリ上コマンド状態.
        user_id (int): 可視ロールを割り当てるユーザーの識別子.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    state.roles_by_id[_VISIBLE_ROLE_ID] = Role(
        id=_VISIBLE_ROLE_ID,
        name="Visible",
        permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
        position=0,
    )
    state.role_ids_by_user_id[user_id] = {_VISIBLE_ROLE_ID}


def _seed_score(
    state: InMemoryCommandRepositoryState,
    *,
    score_id: int,
    user_id: int,
    ruleset: Ruleset = Ruleset.OSU,
    passed: bool = True,
    leaderboard_eligible: bool = True,
) -> None:
    """リプレイ候補テストで参照するスコアを状態へ登録する.

    Args:
        state (InMemoryCommandRepositoryState): 変更対象のメモリ上コマンド状態.
        score_id (int): 登録するスコアの識別子.
        user_id (int): スコア所有者の識別子.
        ruleset (Ruleset): スコアに設定するルールセット.
        passed (bool): スコアを合格済みとして登録するかどうか.
        leaderboard_eligible (bool): スコアをリーダーボード対象として登録するかどうか.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    score = Score(
        id=score_id,
        user_id=user_id,
        beatmap_id=75,
        beatmap_checksum="abc123",
        online_checksum=f"memory-replay-download-{score_id}",
        ruleset=ruleset,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=300,
        n100=2,
        n50=1,
        geki=5,
        katu=4,
        miss=3,
        score=987_654,
        max_combo=1_234,
        accuracy=98.76,
        grade=Grade.S,
        passed=passed,
        perfect=True,
        client_version="b20260618",
        submitted_at=_NOW,
        beatmap_status_at_submission=BeatmapRankStatus.RANKED if passed else None,
        leaderboard_eligible_at_submission=leaderboard_eligible,
    )
    state.scores_by_id[score_id] = score
    state.score_id_by_online_checksum[score.online_checksum] = score_id
    state.score_leaderboard_eligibility_by_id[score_id] = leaderboard_eligible


def _seed_replay(
    state: InMemoryCommandRepositoryState,
    *,
    score_id: int,
    blob_id: int = 123,
    checksum: str = "a" * 64,
    byte_size: int = 4096,
) -> None:
    """指定スコアに紐づくリプレイメタデータを状態へ登録する.

    Args:
        state (InMemoryCommandRepositoryState): 変更対象のメモリ上コマンド状態.
        score_id (int): リプレイを紐づけるスコアの識別子.
        blob_id (int): リプレイ本文を指すblobの識別子.
        checksum (str): リプレイ本文のSHA-256チェックサム.
        byte_size (int): リプレイ本文のバイト数.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    replay_id = len(state.replays_by_id) + 1
    state.replays_by_id[replay_id] = Replay(
        id=replay_id,
        score_id=score_id,
        blob_id=blob_id,
        checksum_sha256=checksum,
        byte_size=byte_size,
    )
    state.replay_id_by_checksum[checksum] = replay_id
