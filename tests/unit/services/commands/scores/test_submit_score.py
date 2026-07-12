"""Tests for score submission command use-case transaction boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, final

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSourceVerification,
)
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.users import User
from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.domain.scores.user_stats import UserStatsScope
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBest,
    BeatmapLeaderboardUserBestScope,
    BeatmapLeaderboardUserScope,
)
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import LeaderboardReadScope
from osu_server.repositories.memory.queries.beatmap_leaderboards import (
    InMemoryBeatmapLeaderboardQueryRepository,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores import (
    SubmitScoreCommand,
    SubmitScoreCommandOutcome,
    SubmitScoreUseCase,
)

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from osu_server.domain.scores.replay import Replay
    from osu_server.repositories.interfaces.commands.replays import ReplayCommandRepository
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork


def _score(
    *,
    online_checksum: str = "online-checksum",
    score: int = 500000,
    max_combo: int = 99,
    accuracy: float = 0.95,
    passed: bool = True,
    leaderboard_eligible_at_submission: bool = True,
    beatmap_checksum: str = "abc123",
    mods: ModCombination | None = None,
) -> Score:
    return Score(
        id=None,
        user_id=1000,
        beatmap_id=1,
        beatmap_checksum=beatmap_checksum,
        online_checksum=online_checksum,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=mods or ModCombination.none(),
        n300=100,
        n100=10,
        n50=5,
        geki=0,
        katu=0,
        miss=2,
        score=score,
        max_combo=max_combo,
        accuracy=accuracy,
        grade=Grade.A,
        passed=passed,
        perfect=False,
        client_version="20240101",
        submitted_at=datetime.now(UTC),
        beatmap_status_at_submission=BeatmapRankStatus.RANKED,
        leaderboard_eligible_at_submission=leaderboard_eligible_at_submission,
    )


@final
class FailingReplayUnitOfWorkFactory:
    """In-memory UoW factory whose replay create fails inside the transaction."""

    def __init__(self) -> None:
        self._factory: InMemoryUnitOfWorkFactory = InMemoryUnitOfWorkFactory()

    def __call__(self) -> AbstractAsyncContextManager[UnitOfWork]:
        context = self._factory()
        return _FailingReplayContext(context)


@final
class _FailingReplayContext:
    def __init__(self, context: AbstractAsyncContextManager[UnitOfWork]) -> None:
        self._context: AbstractAsyncContextManager[UnitOfWork] = context

    async def __aenter__(self) -> UnitOfWork:
        uow = await self._context.__aenter__()
        uow.replays = _FailingReplayRepository(uow.replays)
        return uow

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = await self._context.__aexit__(exc_type, exc, traceback)


@final
class _FailingReplayRepository:
    def __init__(self, wrapped: ReplayCommandRepository) -> None:
        self._wrapped: ReplayCommandRepository = wrapped

    async def create(self, replay: Replay) -> Replay:
        del replay
        raise RuntimeError("replay write failed")

    async def exists_by_checksum(self, checksum: str) -> bool:
        return await self._wrapped.exists_by_checksum(checksum)


@pytest.mark.asyncio
async def test_replay_create_failure_rolls_back_submission_score_and_replay() -> None:
    factory = FailingReplayUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)

    with pytest.raises(RuntimeError, match="replay write failed"):
        _ = await use_case.execute(
            SubmitScoreCommand(
                fingerprint="fingerprint-1",
                user_id=1000,
                beatmap_checksum="abc123",
                submitted_at=datetime.now(UTC),
                outcome=SubmitScoreCommandOutcome.COMPLETED,
                score=_score(),
                beatmap_id=1,
                beatmapset_id=10,
                replay_blob_id=1,
                replay_checksum_sha256="a" * 64,
                replay_byte_size=128,
            )
        )

    async with factory() as uow:
        assert await uow.submissions.get_by_fingerprint("fingerprint-1") is None
        assert await uow.scores.get_by_online_checksum("online-checksum") is None
        assert not await uow.replays.exists_by_checksum("a" * 64)


@pytest.mark.asyncio
async def test_completed_submission_commits_one_snapshot() -> None:
    factory = InMemoryUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)
    beatmap_approved_at = datetime(2026, 6, 29, 12, 34, 56, tzinfo=UTC)

    result = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-2",
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=datetime.now(UTC),
            outcome=SubmitScoreCommandOutcome.COMPLETED,
            score=_score(online_checksum="online-2"),
            beatmap_id=1,
            beatmapset_id=10,
            beatmap_approved_at=beatmap_approved_at,
            replay_blob_id=2,
            replay_checksum_sha256="b" * 64,
            replay_byte_size=256,
            grade_discrepancy={"client_grade": "D", "server_grade": "A"},
            opaque_field_hashes={"fs_sha256": "c" * 64},
        )
    )

    assert result.outcome == SubmitScoreCommandOutcome.COMPLETED
    assert result.score_id == 1
    assert result.score == 500000
    assert result.ruleset is Ruleset.OSU
    assert result.playstyle is Playstyle.VANILLA
    assert result.max_combo == 99
    assert result.accuracy == 0.95
    assert result.passed is True
    assert result.beatmap_playcount == 1
    assert result.beatmap_passcount == 1
    assert result.beatmap_approved_at == beatmap_approved_at
    async with factory() as uow:
        submission = await uow.submissions.get_by_fingerprint("fingerprint-2")
        projection = await uow.current_user_stats.get(
            UserStatsScope(
                user_id=1000,
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
            )
        )
        assert submission is not None
        assert submission.state == "completed"
        assert submission.result_snapshot == {
            "score_id": 1,
            "beatmap_id": 1,
            "beatmapset_id": 10,
            "score": 500000,
            "ruleset": Ruleset.OSU.value,
            "playstyle": Playstyle.VANILLA.value,
            "max_combo": 99,
            "accuracy": 0.95,
            "passed": True,
            "beatmap_playcount": 1,
            "beatmap_passcount": 1,
            "beatmap_approved_at": "2026-06-29T12:34:56+00:00",
            "beatmap_status_at_submission": "ranked",
            "grade_discrepancy": {"client_grade": "D", "server_grade": "A"},
            "opaque_fields": {"fs_sha256": "c" * 64},
            "replay_attachment_id": 1,
            "replay_blob_id": 2,
        }
        assert projection is not None
        assert projection.pp == Decimal("0")
        assert projection.play_count == 1
        assert projection.ranked_score == 500000
        assert projection.total_score == 500000
        assert projection.max_combo == 99
        assert projection.accuracy == 0.0
        assert projection.hit_totals.count_300 == 100
        assert projection.hit_totals.count_100 == 10
        assert projection.hit_totals.count_50 == 5
        assert projection.hit_totals.count_miss == 2

    retry = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-2",
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=datetime.now(UTC),
            outcome=SubmitScoreCommandOutcome.COMPLETED,
            score=_score(online_checksum="online-2-retry"),
            beatmap_id=1,
            beatmapset_id=10,
        )
    )

    assert retry.outcome == SubmitScoreCommandOutcome.COMPLETED
    assert retry.existing_submission is True
    assert retry.ruleset is Ruleset.OSU
    assert retry.playstyle is Playstyle.VANILLA
    assert retry.score == 500000
    assert retry.max_combo == 99
    assert retry.accuracy == 0.95
    assert retry.passed is True
    assert retry.beatmap_playcount == 1
    assert retry.beatmap_passcount == 1
    assert retry.beatmap_approved_at == beatmap_approved_at


@pytest.mark.asyncio
async def test_completed_submission_returns_cumulative_beatmap_play_and_pass_counts() -> None:
    factory = InMemoryUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)

    failed_result = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-count-1",
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=datetime.now(UTC),
            outcome=SubmitScoreCommandOutcome.COMPLETED,
            score=_score(online_checksum="online-count-1", passed=False),
            beatmap_id=1,
            beatmapset_id=10,
        )
    )
    passed_result = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-count-2",
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=datetime.now(UTC),
            outcome=SubmitScoreCommandOutcome.COMPLETED,
            score=_score(online_checksum="online-count-2", passed=True),
            beatmap_id=1,
            beatmapset_id=10,
        )
    )

    assert failed_result.beatmap_playcount == 1
    assert failed_result.beatmap_passcount == 0
    assert passed_result.beatmap_playcount == 2
    assert passed_result.beatmap_passcount == 1


@pytest.mark.asyncio
async def test_eligible_submission_updates_leaderboard_projection_and_snapshot_delta() -> None:
    factory = InMemoryUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)
    first_mods = ModCombination(Mod.HIDDEN | Mod.NIGHTCORE)

    first = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-pb-1",
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=datetime.now(UTC),
            outcome=SubmitScoreCommandOutcome.COMPLETED,
            score=_score(
                online_checksum="online-pb-1",
                score=500000,
                mods=first_mods,
            ),
            beatmap_id=1,
            beatmapset_id=10,
            include_personal_best_delta=True,
            update_personal_best=True,
            personal_best_category=LeaderboardCategory.GLOBAL,
        )
    )

    assert first.personal_best_delta is not None
    assert first.personal_best_delta.before_score is None
    assert first.personal_best_delta.after_score == 500000
    assert first.personal_best_delta.updated is True

    async with factory() as uow:
        first_mod_best = await uow.beatmap_leaderboards.get_user_best(
            BeatmapLeaderboardUserBestScope(
                beatmap_id=1,
                beatmap_checksum="abc123",
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                user_id=1000,
                mods=first_mods,
            )
        )
        global_best = await uow.beatmap_leaderboards.get_global_user_best(
            BeatmapLeaderboardUserScope(
                beatmap_id=1,
                beatmap_checksum="abc123",
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                user_id=1000,
            )
        )

    assert first_mod_best is not None
    assert first_mod_best.score_id == first.score_id
    assert global_best == first_mod_best

    lower = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-pb-2",
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=datetime.now(UTC),
            outcome=SubmitScoreCommandOutcome.COMPLETED,
            score=_score(
                online_checksum="online-pb-2",
                score=400000,
                max_combo=80,
                accuracy=0.9,
            ),
            beatmap_id=1,
            beatmapset_id=10,
            include_personal_best_delta=True,
            update_personal_best=True,
            personal_best_category=LeaderboardCategory.GLOBAL,
        )
    )

    assert lower.personal_best_delta is not None
    assert lower.personal_best_delta.before_score == 500000
    assert lower.personal_best_delta.after_score == 500000
    assert lower.personal_best_delta.updated is False

    async with factory() as uow:
        no_mod_best_after_lower = await uow.beatmap_leaderboards.get_user_best(
            BeatmapLeaderboardUserBestScope(
                beatmap_id=1,
                beatmap_checksum="abc123",
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                user_id=1000,
                mods=ModCombination.none(),
            )
        )
        global_best_after_lower = await uow.beatmap_leaderboards.get_global_user_best(
            BeatmapLeaderboardUserScope(
                beatmap_id=1,
                beatmap_checksum="abc123",
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                user_id=1000,
            )
        )
        lower_submission = await uow.submissions.get_by_fingerprint("fingerprint-pb-2")

    assert no_mod_best_after_lower is not None
    assert no_mod_best_after_lower.score_id == lower.score_id
    assert global_best_after_lower is not None
    assert global_best_after_lower.score_id == first.score_id
    assert lower_submission is not None
    assert lower_submission.result_snapshot is not None
    assert lower_submission.result_snapshot["personal_best_delta"] == {
        "before_score_id": first.score_id,
        "before_score": 500000,
        "before_max_combo": 99,
        "before_accuracy": 0.95,
        "after_score_id": first.score_id,
        "after_score": 500000,
        "after_max_combo": 99,
        "after_accuracy": 0.95,
        "updated": False,
    }

    retry = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-pb-2",
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=datetime.now(UTC),
            outcome=SubmitScoreCommandOutcome.COMPLETED,
            score=_score(online_checksum="online-pb-2-retry", score=900000),
            beatmap_id=1,
            beatmapset_id=10,
            include_personal_best_delta=True,
            update_personal_best=True,
            personal_best_category=LeaderboardCategory.GLOBAL,
        )
    )

    async with factory() as uow:
        no_mod_best_after_retry = await uow.beatmap_leaderboards.get_user_best(
            BeatmapLeaderboardUserBestScope(
                beatmap_id=1,
                beatmap_checksum="abc123",
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                user_id=1000,
                mods=ModCombination.none(),
            )
        )

    assert retry.existing_submission is True
    assert retry.score_id == lower.score_id
    assert retry.personal_best_delta == lower.personal_best_delta
    assert no_mod_best_after_retry == no_mod_best_after_lower


@pytest.mark.asyncio
async def test_submission_persists_leaderboard_eligibility_snapshot() -> None:
    factory = InMemoryUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)

    result = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-ineligible-stored",
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=datetime.now(UTC),
            outcome=SubmitScoreCommandOutcome.COMPLETED,
            score=_score(
                online_checksum="online-ineligible-stored",
                leaderboard_eligible_at_submission=False,
            ),
            beatmap_id=1,
            beatmapset_id=10,
        )
    )

    assert result.outcome == SubmitScoreCommandOutcome.COMPLETED
    assert result.score_id is not None

    async with factory() as uow:
        stored_score = await uow.scores.get_by_id(result.score_id)

    assert stored_score is not None
    assert stored_score.leaderboard_eligible_at_submission is False
    assert factory.snapshot().score_leaderboard_eligibility_by_id[result.score_id] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("candidate_passed", "candidate_eligible"),
    [
        pytest.param(False, False, id="failed"),
        pytest.param(True, False, id="submission-time-ineligible"),
    ],
)
async def test_ineligible_submission_does_not_update_submit_personal_best_delta(
    *,
    candidate_passed: bool,
    candidate_eligible: bool,
) -> None:
    factory = InMemoryUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)

    first = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-existing-pb",
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=datetime.now(UTC),
            outcome=SubmitScoreCommandOutcome.COMPLETED,
            score=_score(online_checksum="online-existing-pb", score=500000),
            beatmap_id=1,
            beatmapset_id=10,
            include_personal_best_delta=True,
            update_personal_best=True,
            personal_best_category=LeaderboardCategory.GLOBAL,
        )
    )
    assert first.score_id is not None

    candidate = await use_case.execute(
        SubmitScoreCommand(
            fingerprint=f"fingerprint-candidate-{candidate_passed}-{candidate_eligible}",
            user_id=1000,
            beatmap_checksum="abc123",
            submitted_at=datetime.now(UTC),
            outcome=SubmitScoreCommandOutcome.COMPLETED,
            score=_score(
                online_checksum=f"online-candidate-{candidate_passed}-{candidate_eligible}",
                score=900000,
                passed=candidate_passed,
                leaderboard_eligible_at_submission=candidate_eligible,
            ),
            beatmap_id=1,
            beatmapset_id=10,
            include_personal_best_delta=True,
            update_personal_best=True,
            personal_best_category=LeaderboardCategory.GLOBAL,
        )
    )

    async with factory() as uow:
        all_mods_best = await uow.beatmap_leaderboards.get_user_best(
            BeatmapLeaderboardUserBestScope(
                beatmap_id=1,
                beatmap_checksum="abc123",
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                user_id=1000,
                mods=ModCombination.none(),
            )
        )

    assert candidate.score_id is not None
    assert candidate.personal_best_delta is None
    assert all_mods_best is not None
    assert all_mods_best.score_id == first.score_id


@pytest.mark.asyncio
async def test_stored_but_ineligible_submission_is_not_returned_from_leaderboard_rows() -> None:
    factory = InMemoryUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)
    beatmap_checksum = "a" * 32

    result = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-pre-promotion",
            user_id=1000,
            beatmap_checksum=beatmap_checksum,
            submitted_at=datetime.now(UTC),
            outcome=SubmitScoreCommandOutcome.COMPLETED,
            score=_score(
                online_checksum="online-pre-promotion",
                beatmap_checksum=beatmap_checksum,
                leaderboard_eligible_at_submission=False,
            ),
            beatmap_id=1,
            beatmapset_id=10,
        )
    )
    assert result.score_id is not None

    state = factory.snapshot()
    state.users_by_id[1000] = User(
        id=1000,
        username="Player",
        safe_username="player",
        email="player@example.com",
        password_hash="hash",
        country="JP",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    state.roles_by_id[1] = Role(
        id=1,
        name="Visible",
        permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
        position=1,
    )
    state.role_ids_by_user_id[1000] = {1}
    state.beatmaps_by_id[1] = Beatmap(
        id=1,
        beatmapset_id=10,
        checksum_md5=beatmap_checksum,
        mode=BeatmapMode.OSU,
        version="Insane",
        total_length=None,
        hit_length=None,
        max_combo=None,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.AVAILABLE,
        file_attachment=None,
        last_fetched_at=datetime.now(UTC),
        next_refresh_at=None,
    )
    state.beatmap_id_by_checksum[beatmap_checksum] = 1
    state.beatmap_leaderboard_user_bests_by_id[result.score_id] = BeatmapLeaderboardUserBest(
        id=result.score_id,
        scope=BeatmapLeaderboardUserBestScope(
            beatmap_id=1,
            beatmap_checksum=beatmap_checksum,
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
            user_id=1000,
            mods=ModCombination.none(),
        ),
        score_id=result.score_id,
        rank_key=ScoreRankKey(
            score=900000,
            submitted_at=datetime.now(UTC),
            score_id=result.score_id,
        ),
    )
    state.beatmap_leaderboard_user_best_id_by_scope[
        (1, Ruleset.OSU.value, Playstyle.VANILLA.value, 1000, int(Mod.NONE))
    ] = result.score_id
    factory.commit_state(state)

    repository = InMemoryBeatmapLeaderboardQueryRepository(factory)
    rows = await repository.list_top_rows(
        LeaderboardReadScope(
            beatmap_id=1,
            beatmap_checksum=beatmap_checksum,
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
            category=LeaderboardCategory.GLOBAL,
            country=None,
            eligible_user_ids=None,
        ),
        limit=50,
    )

    async with factory() as uow:
        stored_score = await uow.scores.get_by_id(result.score_id)

    assert stored_score is not None
    assert stored_score.leaderboard_eligible_at_submission is False
    assert rows == ()
