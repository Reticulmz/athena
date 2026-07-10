"""In-memory replay download query repository の tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

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
    committed_state = InMemoryCommandRepositoryState()
    factory = InMemoryUnitOfWorkFactory(committed_state)
    repository = InMemoryReplayDownloadQueryRepository(
        InMemoryQueryStateSnapshotProvider(committed_state)
    )
    return factory, factory.snapshot(), repository


def _seed_visible_role(state: InMemoryCommandRepositoryState, *, user_id: int) -> None:
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
        beatmap_status_at_submission="ranked" if passed else None,
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
    replay_id = len(state.replays_by_id) + 1
    state.replays_by_id[replay_id] = Replay(
        id=replay_id,
        score_id=score_id,
        blob_id=blob_id,
        checksum_sha256=checksum,
        byte_size=byte_size,
    )
    state.replay_id_by_checksum[checksum] = replay_id
