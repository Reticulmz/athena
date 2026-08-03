"""InMemoryScoreCommandRepositoryのcommand契約を検証するtests."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, PlayTimeSource, Ruleset, Score
from osu_server.repositories.memory.commands.scores import InMemoryScoreCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


@pytest.fixture
def repository() -> InMemoryScoreCommandRepository:
    """testごとに独立したInMemoryScoreCommandRepositoryを提供する.

    Returns:
        InMemoryScoreCommandRepository: 空のcommand stateを持つrepository.
    """
    return InMemoryScoreCommandRepository(InMemoryCommandRepositoryState())


@pytest.fixture
def sample_score() -> Score:
    """Score commandの検証に使う保存前Score fixtureを提供する.

    Returns:
        Score: osu vanillaの固定fieldを持つ保存前score.
    """
    return Score(
        id=None,
        user_id=1,
        beatmap_id=100,
        beatmap_checksum="abc123",
        online_checksum="online_abc123",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=500,
        n100=50,
        n50=10,
        geki=100,
        katu=20,
        miss=5,
        score=1_000_000,
        max_combo=300,
        accuracy=0.95,
        grade=Grade.A,
        passed=True,
        perfect=False,
        client_version="b20240101",
        submitted_at=datetime.now(UTC),
    )


class TestCreate:
    """Score create操作のID割当と一意制約を検証するtest群."""

    async def test_create_assigns_id(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """空のrepositoryが最初の保存scoreへID 1を割り当てることを検証する.

        保存前scoreをcreateし, 返却scoreがNoneではない最初のIDを持つことを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): 保存操作を実行する空repository.
            sample_score (Score): 保存するID未割当score fixture.

        Returns:
            None: 割り当てられたIDを検証して完了し, 呼び出し側へ値を返さない.
        """
        created = await repository.create(sample_score)
        assert created.id is not None
        assert created.id == 1

    async def test_create_increments_id(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """異なるscoreを連続保存するとIDが単調増加することを検証する.

        異なるonline checksumを持つ2 scoreをcreateし, 返却IDが1と2になることを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): 連続保存を実行する空repository.
            sample_score (Score): 最初に保存するscore fixture.

        Returns:
            None: 連続IDの割当結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        score1 = await repository.create(sample_score)
        score2 = await repository.create(replace(sample_score, online_checksum="online_xyz789"))
        assert score1.id == 1
        assert score2.id == 2

    async def test_create_rejects_duplicate_online_checksum(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """既存online checksumを再利用したcreateが拒否されることを検証する.

        同じscoreを2回保存し, 2回目のcreateがchecksum重複を示すValueErrorを送出することを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): checksum一意制約を持つrepository.
            sample_score (Score): 2回保存を試みるscore fixture.

        Returns:
            None: 重複入力の例外を検証して完了し, 呼び出し側へ値を返さない.
        """
        _ = await repository.create(sample_score)
        with pytest.raises(ValueError, match="online_checksum already exists"):
            _ = await repository.create(sample_score)


class TestExistsByOnlineChecksum:
    """online checksum存在確認のbool契約を検証するtest群."""

    async def test_returns_false_when_not_exists(
        self, repository: InMemoryScoreCommandRepository
    ) -> None:
        """未保存checksumの存在確認がFalseになることを検証する.

        空のrepositoryへ任意checksumを問い合わせ, scoreが合成されずFalseを返すことを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): 空の存在確認対象repository.

        Returns:
            None: 未発見時のbool結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        exists = await repository.exists_by_online_checksum("nonexistent")
        assert exists is False

    async def test_returns_true_when_exists(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """保存済みchecksumの存在確認がTrueになることを検証する.

        scoreを保存した後に同じonline checksumを問い合わせ, Trueが返ることを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): 保存と存在確認を行うrepository.
            sample_score (Score): checksumを登録するscore fixture.

        Returns:
            None: 保存済みchecksumのbool結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        _ = await repository.create(sample_score)
        exists = await repository.exists_by_online_checksum(sample_score.online_checksum)
        assert exists is True


class TestGetByOnlineChecksum:
    """online checksum lookupのoptional Score契約を検証するtest群."""

    async def test_returns_none_when_not_found(
        self, repository: InMemoryScoreCommandRepository
    ) -> None:
        """未保存checksumのlookupがNoneになることを検証する.

        空のrepositoryへ任意checksumを問い合わせ, 未発見をNoneで表すことを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): 空のlookup対象repository.

        Returns:
            None: 未発見時のoptional結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        score = await repository.get_by_online_checksum("nonexistent")
        assert score is None

    async def test_returns_score_when_found(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """保存済みchecksumのlookupが同じScoreを返すことを検証する.

        scoreを保存後にそのonline checksumで取得し, IDとchecksumが保存結果と一致することを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): 保存とlookupを行うrepository.
            sample_score (Score): checksumで識別するscore fixture.

        Returns:
            None: 保存済みScoreのlookup結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        created = await repository.create(sample_score)
        retrieved = await repository.get_by_online_checksum(sample_score.online_checksum)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.online_checksum == sample_score.online_checksum


class TestGetById:
    """ID lookupのoptional Scoreとfield保持を検証するtest群."""

    async def test_returns_none_when_not_found(
        self, repository: InMemoryScoreCommandRepository
    ) -> None:
        """未知IDのlookupがNoneになることを検証する.

        空のrepositoryへ未割当IDを問い合わせ, 未発見をNoneで表すことを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): 空のID lookup対象repository.

        Returns:
            None: 未発見時のoptional結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        score = await repository.get_by_id(999)
        assert score is None

    async def test_returns_score_when_found(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """保存済みIDのlookupが同じScoreを返すことを検証する.

        scoreを保存して返却IDで取得し, IDとonline checksumが保存結果と一致することを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): 保存とID lookupを行うrepository.
            sample_score (Score): IDを割り当てるscore fixture.

        Returns:
            None: 保存済みScoreのID lookup結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        created = await repository.create(sample_score)
        assert created.id is not None
        retrieved = await repository.get_by_id(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.online_checksum == created.online_checksum

    async def test_returns_score_with_timing_fields(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """ID lookupがsubmit timing fieldを保持することを検証する.

        fail timeとplay timeを持つscoreを保存して取得し,
        時間値とsourceとexit classificationが不変なことを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): 保存とID lookupを行うrepository.
            sample_score (Score): timing fieldを差し替える基底score fixture.

        Returns:
            None: timing fieldの保持を検証して完了し, 呼び出し側へ値を返さない.
        """
        score = replace(
            sample_score,
            fail_time_ms=7_112,
            play_time_seconds=7,
            play_time_source=PlayTimeSource.FAIL_TIME,
            submit_exit_classification="1",
        )

        created = await repository.create(score)
        assert created.id is not None
        retrieved = await repository.get_by_id(created.id)

        assert retrieved is not None
        assert retrieved.fail_time_ms == 7_112
        assert retrieved.play_time_seconds == 7
        assert retrieved.play_time_source is PlayTimeSource.FAIL_TIME
        assert retrieved.submit_exit_classification == "1"


class TestCountSubmissionsForBeatmap:
    """beatmap提出数集計のscopeと空結果を検証するtest群."""

    async def test_counts_all_plays_and_passed_scores_for_target_beatmap(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """対象beatmapのplay数とpass数だけを集計することを検証する.

        同一beatmapのpassed scoreとfailed scoreおよび別beatmapのscoreを保存し,
        対象集計が2 playと1 passになることを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): scoreを保存して集計するrepository.
            sample_score (Score): 対象beatmapの基底score fixture.

        Returns:
            None: beatmap scope内のsubmitted countを検証して完了し, 呼び出し側へ値を返さない.
        """
        _ = await repository.create(sample_score)
        _ = await repository.create(replace(sample_score, online_checksum="failed", passed=False))
        _ = await repository.create(
            replace(sample_score, online_checksum="other-beatmap", beatmap_id=101)
        )

        counts = await repository.count_submissions_for_beatmap(100)

        assert counts.play_count == 2
        assert counts.pass_count == 1

    async def test_returns_zero_counts_for_unknown_beatmap(
        self, repository: InMemoryScoreCommandRepository
    ) -> None:
        """scoreがないbeatmapの提出数を0として返すことを検証する.

        空のrepositoryで任意beatmapを集計し, play数とpass数がともに0になることを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): 空の集計対象repository.

        Returns:
            None: 空scopeのcountを検証して完了し, 呼び出し側へ値を返さない.
        """
        counts = await repository.count_submissions_for_beatmap(100)

        assert counts.play_count == 0
        assert counts.pass_count == 0


class TestIncrementReplayViewCount:
    """replay view count更新の成功と未発見結果を検証するtest群."""

    async def test_increments_existing_score_count(
        self, repository: InMemoryScoreCommandRepository, sample_score: Score
    ) -> None:
        """保存済みscoreのreplay view countを1増やすことを検証する.

        初期count 2のscoreを更新して再取得し, countが3になりscore識別子が保持されることを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): count更新を実行するrepository.
            sample_score (Score): replay view countを持つscoreの基底fixture.

        Returns:
            None: 成功結果と更新済みcountを検証して完了し, 呼び出し側へ値を返さない.
        """
        created = await repository.create(replace(sample_score, replay_view_count=2))
        assert created.id is not None

        incremented = await repository.increment_replay_view_count(created.id)

        updated = await repository.get_by_id(created.id)
        assert incremented is True
        assert updated is not None
        assert updated.replay_view_count == 3
        assert updated.online_checksum == created.online_checksum

    async def test_returns_false_when_score_missing(
        self, repository: InMemoryScoreCommandRepository
    ) -> None:
        """未保存scoreのreplay view count更新がFalseになることを検証する.

        空のrepositoryへ未割当IDの更新を要求し, stateを作らずFalseを返すことを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): 空の更新対象repository.

        Returns:
            None: 未発見時のbool結果を検証して完了し, 呼び出し側へ値を返さない.
        """
        incremented = await repository.increment_replay_view_count(999)

        assert incremented is False


class TestListCurrentStatsScoresForUser:
    """CurrentUserStats入力scoreのfilter条件を検証するtest群."""

    async def test_filters_user_mode_and_excludes_relax_autopilot(
        self,
        repository: InMemoryScoreCommandRepository,
        sample_score: Score,
    ) -> None:
        """CurrentUserStats対象のuser, ruleset, playstyleだけを返すことを検証する.

        他user, 別ruleset, Relax, Autopilotのscoreを保存し,
        vanilla osuの対象scoreだけがlistingに残ることを確認する.

        Args:
            repository (InMemoryScoreCommandRepository): scoreを保存してfilterするrepository.
            sample_score (Score): 対象userのvanilla osu score fixture.

        Returns:
            None: CurrentUserStats入力listingを検証して完了し, 呼び出し側へ値を返さない.
        """
        included = await repository.create(sample_score)
        _ = await repository.create(replace(sample_score, online_checksum="other-user", user_id=2))
        _ = await repository.create(
            replace(
                sample_score,
                online_checksum="other-ruleset",
                ruleset=Ruleset.MANIA,
            )
        )
        _ = await repository.create(
            replace(
                sample_score,
                online_checksum="relax",
                mods=ModCombination(Mod.RELAX),
            )
        )
        _ = await repository.create(
            replace(
                sample_score,
                online_checksum="autopilot",
                mods=ModCombination(Mod.AUTOPILOT),
            )
        )

        scores = await repository.list_current_stats_scores_for_user(
            1,
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
        )

        assert scores == (included,)
