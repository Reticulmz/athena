"""score submission command use caseのtransaction境界をUnit testで検証する."""

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

_BEATMAP_CHECKSUM = "a" * 32


def _score(
    *,
    online_checksum: str = "online-checksum",
    score: int = 500000,
    max_combo: int = 99,
    accuracy: float = 0.95,
    passed: bool = True,
    leaderboard_eligible_at_submission: bool = True,
    beatmap_checksum: str = _BEATMAP_CHECKSUM,
    mods: ModCombination | None = None,
) -> Score:
    """Completed submissionに渡すtest用scoreを作成する.

    Args:
        online_checksum (str): scoreの一意なonline checksum.
        score (int): 記録するtotal score値.
        max_combo (int): 記録する最大combo数.
        accuracy (float): 記録するaccuracy値.
        passed (bool): scoreがpass済みか.
        leaderboard_eligible_at_submission (bool): submission時にleaderboard対象だったか.
        beatmap_checksum (str): score対象beatmapのchecksum.
        mods (ModCombination | None): scoreに適用するmod組み合わせ. 未指定時はno-mod.

    Returns:
        Score: memory Unit of Workへ永続化できるtest用score.
    """
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
    """replay作成だけがtransaction内で失敗するmemory UoW factoryを提供する.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): contextを生成するwrapped memory factory.
    """

    def __init__(self) -> None:
        """Wrapped memory Unit of Work factoryを初期化する."""
        self._factory: InMemoryUnitOfWorkFactory = InMemoryUnitOfWorkFactory()

    def __call__(self) -> AbstractAsyncContextManager[UnitOfWork]:
        """Replay repositoryを失敗fakeへ差し替えるUnit of Work contextを返す.

        Returns:
            AbstractAsyncContextManager[UnitOfWork]: replay作成時に例外を送出するcontext.
        """
        context = self._factory()
        return _FailingReplayContext(context)


@final
class _FailingReplayContext:
    """enter時にreplay repositoryを失敗fakeへ置換するcontext wrapperを提供する.

    Attributes:
        _context (AbstractAsyncContextManager[UnitOfWork]): wrapped Unit of Work context.
    """

    def __init__(self, context: AbstractAsyncContextManager[UnitOfWork]) -> None:
        """Wrapped Unit of Work contextを保持する.

        Args:
            context (AbstractAsyncContextManager[UnitOfWork]): replay repositoryを差し替える対象
                context.
        """
        self._context: AbstractAsyncContextManager[UnitOfWork] = context

    async def __aenter__(self) -> UnitOfWork:
        """Wrapped Unit of Workへ入り,replay repositoryを失敗fakeへ差し替える.

        Returns:
            UnitOfWork: replay createでRuntimeErrorを送出するUnit of Work.
        """
        uow = await self._context.__aenter__()
        uow.replays = _FailingReplayRepository(uow.replays)
        return uow

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Wrapped contextへ例外情報を渡して退出する.

        Args:
            exc_type (type[BaseException] | None): context内で送出された例外型.
            exc (BaseException | None): context内で送出された例外instance.
            traceback (TracebackType | None): context内例外のtraceback.

        Returns:
            None: wrapped contextの終了処理を実行して,呼び出し側へ値を返さずに完了する.
        """
        _ = await self._context.__aexit__(exc_type, exc, traceback)


@final
class _FailingReplayRepository:
    """createだけを失敗させ,checksum照会はwrapped repositoryへ委譲するfakeを提供する.

    Attributes:
        _wrapped (ReplayCommandRepository): checksum照会に利用する実repository.
    """

    def __init__(self, wrapped: ReplayCommandRepository) -> None:
        """checksum照会を委譲するreplay repositoryを保持する.

        Args:
            wrapped (ReplayCommandRepository): create以外を委譲するrepository.
        """
        self._wrapped: ReplayCommandRepository = wrapped

    async def create(self, replay: Replay) -> Replay:
        """replay永続化障害を送出してtransaction rollbackを検証可能にする.

        Args:
            replay (Replay): 未永続化のreplay.

        Raises:
            RuntimeError: replay write failureを再現する場合.
        """
        del replay
        raise RuntimeError("replay write failed")

    async def exists_by_checksum(self, checksum: str) -> bool:
        """checksum存在照会をwrapped repositoryへ委譲する.

        Args:
            checksum (str): 存在確認するreplay checksum.

        Returns:
            bool: wrapped repositoryが返すchecksum存在結果.
        """
        return await self._wrapped.exists_by_checksum(checksum)


@pytest.mark.asyncio
async def test_replay_create_failure_rolls_back_submission_score_and_replay() -> None:
    """replay作成障害がsubmission,score,replayを全てrollbackする契約を検証する.

    replay createがRuntimeErrorを送出するUnit of Work factoryで
    completed submissionを実行する条件で,例外が伝播し,fingerprint,score checksum,
    replay checksumの永続stateが空であることを確認する.

    Returns:
        None: transaction rollback後の永続stateを検証して,呼び出し側へ値を返さずに完了する.
    """
    factory = FailingReplayUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)

    with pytest.raises(RuntimeError, match="replay write failed"):
        _ = await use_case.execute(
            SubmitScoreCommand(
                fingerprint="fingerprint-1",
                user_id=1000,
                beatmap_checksum=_BEATMAP_CHECKSUM,
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
    """Completed submissionが一つのresult snapshotをcommitしretryで再利用する契約を検証する.

    replay metadataとscore詳細を持つcompleted commandを実行し,同じfingerprintでretryする条件で,
    submission snapshot,current user stats,初回result,
    および既存submission resultが一致することを確認する.

    Returns:
        None: committed snapshotとidempotent retryの観測結果を検証して,呼び出し側へ値を返さずに
            完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)
    beatmap_approved_at = datetime(2026, 6, 29, 12, 34, 56, tzinfo=UTC)

    result = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-2",
            user_id=1000,
            beatmap_checksum=_BEATMAP_CHECKSUM,
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
            beatmap_checksum=_BEATMAP_CHECKSUM,
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
    """Completed submissionが累積beatmap play数とpass数を返す契約を検証する.

    failed scoreとpassed scoreを同じbeatmapへ順にsubmitする条件で,各resultが累積play countと
    passed scoreだけを反映した累積pass countを返すことを確認する.

    Returns:
        None: 二つのsubmission resultに含まれる累積countを検証して,呼び出し側へ値を返さずに
            完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)

    failed_result = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-count-1",
            user_id=1000,
            beatmap_checksum=_BEATMAP_CHECKSUM,
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
            beatmap_checksum=_BEATMAP_CHECKSUM,
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
    """Eligible submissionがleaderboard projectionとpersonal best snapshotを更新する契約を検証する.

    最初のmod付きscore,より低いno-mod score,同じfingerprintのretryをsubmitする条件で,mod scopeと
    global scopeのbest,personal best delta snapshot,idempotent retryが既存resultを保持することを
    確認する.

    Returns:
        None: projection,snapshot delta,retry後stateを検証して,呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)
    first_mods = ModCombination(Mod.HIDDEN | Mod.NIGHTCORE)

    first = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-pb-1",
            user_id=1000,
            beatmap_checksum=_BEATMAP_CHECKSUM,
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
                beatmap_checksum=_BEATMAP_CHECKSUM,
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                user_id=1000,
                mods=first_mods,
            )
        )
        global_best = await uow.beatmap_leaderboards.get_global_user_best(
            BeatmapLeaderboardUserScope(
                beatmap_id=1,
                beatmap_checksum=_BEATMAP_CHECKSUM,
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
            beatmap_checksum=_BEATMAP_CHECKSUM,
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
                beatmap_checksum=_BEATMAP_CHECKSUM,
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                user_id=1000,
                mods=ModCombination.none(),
            )
        )
        global_best_after_lower = await uow.beatmap_leaderboards.get_global_user_best(
            BeatmapLeaderboardUserScope(
                beatmap_id=1,
                beatmap_checksum=_BEATMAP_CHECKSUM,
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
            beatmap_checksum=_BEATMAP_CHECKSUM,
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
                beatmap_checksum=_BEATMAP_CHECKSUM,
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
    """submission時のleaderboard eligibilityがscoreとsnapshotへ固定される契約を検証する.

    eligibilityがFalseのcompleted scoreをsubmitする条件で,永続scoreとscore eligibility snapshotが
    どちらもFalseとして観測できることを確認する.

    Returns:
        None: submission時eligibilityの永続化を検証して,呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)

    result = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-ineligible-stored",
            user_id=1000,
            beatmap_checksum=_BEATMAP_CHECKSUM,
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
    """Ineligible submissionがpersonal best deltaとbest rowを更新しない契約を検証する.

    既存eligible bestの後にfailedまたはsubmission時ineligibleな高scoreをsubmitする条件で,
    候補resultのpersonal best deltaがNoneとなり,既存all-mod bestが保持されることを確認する.

    Args:
        candidate_passed (bool): 候補scoreがpass済みかを表すparameterized条件.
        candidate_eligible (bool): 候補scoreがsubmission時にleaderboard対象かを表す条件.

    Returns:
        None: ineligible候補後のpersonal best非更新を検証して,呼び出し側へ値を返さずに完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    use_case = SubmitScoreUseCase(unit_of_work_factory=factory)

    first = await use_case.execute(
        SubmitScoreCommand(
            fingerprint="fingerprint-existing-pb",
            user_id=1000,
            beatmap_checksum=_BEATMAP_CHECKSUM,
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
            beatmap_checksum=_BEATMAP_CHECKSUM,
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
                beatmap_checksum=_BEATMAP_CHECKSUM,
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
    """保存済みでもineligibleなscoreをleaderboard queryが返さない契約を検証する.

    submission時eligibilityがFalseのscoreに可視user,beatmap,best rowを後から設定する条件で,
    score自体は保持されつつglobal leaderboard rowが空になることを確認する.

    Returns:
        None: eligibility snapshotに基づくquery除外を検証して,呼び出し側へ値を返さずに完了する.
    """
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
