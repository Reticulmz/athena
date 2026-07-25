"""UserStats query repositoryのsource read契約を検証するtests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.users import User
from osu_server.domain.scores import Grade, Mod, ModCombination, Playstyle, Ruleset, Score
from osu_server.domain.scores.user_stats import (
    UserPerformanceBest,
    UserStatsHitTotals,
    UserStatsProjection,
    UserStatsScope,
)
from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
    BeatmapPerformanceBest,
    BeatmapPerformanceBestScope,
)
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.user_stats import InMemoryUserStatsQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

_NOW = datetime(2026, 6, 28, 0, 0, 0, tzinfo=UTC)
_VISIBLE_ROLE_ID = 1
_HIDDEN_ROLE_ID = 2


@pytest.mark.asyncio
async def test_reads_empty_known_users_and_omits_unknown_users() -> None:
    """既知userの空統計を返し未知userと重複入力を除く契約を検証する.

    可視roleを持つ1 userだけを保存してIDを重複させたqueryを送り,
    0値のsourceを1件だけ返すことを確認する.

    Returns:
        None: user存在判定と空統計のread結果を検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = _factory()
    state = factory.snapshot()
    _seed_visible_role(state)
    state.users_by_id[10] = _user(10)
    state.role_ids_by_user_id[10] = {_VISIBLE_ROLE_ID}
    factory.commit_state(state)
    repository = InMemoryUserStatsQueryRepository(factory)

    result = await repository.read_current_stats_sources((10, 999, 10))

    assert [source.user_id for source in result.users] == [10]
    assert result.users[0].play_count == 0
    assert result.users[0].ranked_score == 0
    assert result.users[0].total_score == 0
    assert result.users[0].play_time_seconds is None
    assert result.users[0].best_performances == ()
    assert [candidate.user_id for candidate in result.rank_inputs] == []


@pytest.mark.asyncio
async def test_reads_score_totals_and_excludes_relax_autopilot_from_initial_stats() -> None:
    """初期UserStats集計がRelaxとAutopilot scoreを除外する契約を検証する.

    passed, failed, 非eligible, Relax, Autopilot scoreを保存し,
    play数とscore totalsとhit totalsが対象scoreだけを反映することを確認する.

    Returns:
        None: 初期統計のscore filterと集計値を検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = _factory()
    state = factory.snapshot()
    _seed_visible_role(state)
    state.users_by_id[10] = _user(10)
    state.role_ids_by_user_id[10] = {_VISIBLE_ROLE_ID}
    state.scores_by_id[1] = _score(
        score_id=1,
        score=100,
        max_combo=200,
        play_time_seconds=30,
    )
    state.scores_by_id[2] = _score(
        score_id=2,
        score=200,
        max_combo=700,
        play_time_seconds=None,
    )
    state.scores_by_id[3] = _score(
        score_id=3,
        score=300,
        max_combo=500,
        passed=False,
        play_time_seconds=20,
    )
    state.scores_by_id[4] = _score(
        score_id=4,
        score=400,
        max_combo=999,
        mods=ModCombination(Mod.RELAX),
        play_time_seconds=40,
    )
    state.scores_by_id[5] = _score(
        score_id=5,
        score=500,
        max_combo=999,
        mods=ModCombination(Mod.AUTOPILOT),
        play_time_seconds=50,
    )
    state.scores_by_id[6] = _score(
        score_id=6,
        score=600,
        max_combo=600,
        leaderboard_eligible_at_submission=False,
        play_time_seconds=60,
    )
    factory.commit_state(state)
    repository = InMemoryUserStatsQueryRepository(factory)

    result = await repository.read_current_stats_sources((10,))

    source = result.users[0]
    assert source.play_count == 4
    assert source.total_score == 1200
    assert source.ranked_score == 200
    assert source.max_combo == 700
    assert source.play_time_seconds == 110
    assert source.hit_totals == UserStatsHitTotals(
        count_300=1200,
        count_100=80,
        count_50=20,
    )


@pytest.mark.asyncio
async def test_reads_scores_bests_and_rank_inputs_for_requested_ruleset_only() -> None:
    """Requested rulesetだけのscoreとperformance bestをsourceへ読む契約を検証する.

    osuとmaniaのscoreおよび複数userのbestを保存し,
    mania queryが対象userのmania値とrank inputだけを返すことを確認する.

    Returns:
        None: ruleset scopeのsourceとrank inputを検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = _factory()
    state = factory.snapshot()
    _seed_visible_role(state)
    state.users_by_id[10] = _user(10)
    state.users_by_id[20] = _user(20)
    state.role_ids_by_user_id[10] = {_VISIBLE_ROLE_ID}
    state.role_ids_by_user_id[20] = {_VISIBLE_ROLE_ID}
    state.scores_by_id[1] = _score(score_id=1, score=100, max_combo=500, play_time_seconds=10)
    state.scores_by_id[2] = _score(
        score_id=2,
        score=300,
        max_combo=800,
        ruleset=Ruleset.MANIA,
        play_time_seconds=30,
    )
    state.beatmap_performance_bests_by_id[1] = _best(
        row_id=1,
        user_id=10,
        beatmap_id=100,
        pp=Decimal("50"),
        accuracy=0.90,
    )
    state.beatmap_performance_bests_by_id[2] = _best(
        row_id=2,
        user_id=10,
        beatmap_id=101,
        pp=Decimal("120"),
        accuracy=0.99,
        ruleset=Ruleset.MANIA,
    )
    state.beatmap_performance_bests_by_id[3] = _best(
        row_id=3,
        user_id=20,
        beatmap_id=100,
        pp=Decimal("999"),
        accuracy=1.0,
    )
    factory.commit_state(state)
    repository = InMemoryUserStatsQueryRepository(factory)

    result = await repository.read_current_stats_sources(
        (10,),
        ruleset=Ruleset.MANIA,
        playstyle=Playstyle.VANILLA,
    )

    assert len(result.users) == 1
    assert result.users[0].play_count == 1
    assert result.users[0].ranked_score == 300
    assert result.users[0].total_score == 300
    assert result.users[0].max_combo == 800
    assert result.users[0].play_time_seconds == 30
    assert result.users[0].best_performances == (
        UserPerformanceBest(pp=Decimal("120"), accuracy=0.99),
    )
    assert [candidate.user_id for candidate in result.rank_inputs] == [10]


@pytest.mark.asyncio
async def test_reads_best_performances_and_rank_inputs_for_visible_users_only() -> None:
    """Performance best sourceとrank inputのvisibility境界を検証する.

    visible roleとhidden roleのuserにbestを保存し,
    sourceは各userのbestを返してrank inputはvisible userだけにすることを確認する.

    Returns:
        None: visible userだけのrank inputを検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = _factory()
    state = factory.snapshot()
    _seed_visible_role(state)
    _seed_hidden_role(state)
    state.users_by_id[10] = _user(10)
    state.users_by_id[20] = _user(20)
    state.users_by_id[30] = _user(30)
    state.role_ids_by_user_id[10] = {_VISIBLE_ROLE_ID}
    state.role_ids_by_user_id[20] = {_VISIBLE_ROLE_ID}
    state.role_ids_by_user_id[30] = {_HIDDEN_ROLE_ID}
    state.beatmap_performance_bests_by_id[1] = _best(
        row_id=1,
        user_id=10,
        beatmap_id=100,
        pp=Decimal("120"),
        accuracy=0.99,
    )
    state.beatmap_performance_bests_by_id[2] = _best(
        row_id=2,
        user_id=10,
        beatmap_id=101,
        pp=Decimal("80"),
        accuracy=0.95,
    )
    state.beatmap_performance_bests_by_id[3] = _best(
        row_id=3,
        user_id=20,
        beatmap_id=100,
        pp=Decimal("120"),
        accuracy=0.98,
    )
    state.beatmap_performance_bests_by_id[4] = _best(
        row_id=4,
        user_id=30,
        beatmap_id=100,
        pp=Decimal("999"),
        accuracy=1.0,
    )
    factory.commit_state(state)
    repository = InMemoryUserStatsQueryRepository(factory)

    result = await repository.read_current_stats_sources((10, 20, 30))

    sources = {source.user_id: source for source in result.users}
    assert sources[10].best_performances == (
        UserPerformanceBest(pp=Decimal("120"), accuracy=0.99),
        UserPerformanceBest(pp=Decimal("80"), accuracy=0.95),
    )
    assert sources[20].best_performances == (
        UserPerformanceBest(pp=Decimal("120"), accuracy=0.98),
    )
    assert sources[30].best_performances == (UserPerformanceBest(pp=Decimal("999"), accuracy=1.0),)
    assert [candidate.user_id for candidate in result.rank_inputs] == [10, 20]
    assert [candidate.best_performances[0].pp for candidate in result.rank_inputs] == [
        Decimal("120"),
        Decimal("120"),
    ]


@pytest.mark.asyncio
async def test_reads_current_stats_projection_before_source_fallback() -> None:
    """保存済みCurrentUserStats projectionをsource集計より優先する契約を検証する.

    scoreとbestがあるuserへ異なるprojectionを保存し,
    read結果がprojection値とprojection由来rank inputを返すことを確認する.

    Returns:
        None: projection優先のsource結果を検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = _factory()
    state = factory.snapshot()
    _seed_visible_role(state)
    state.users_by_id[10] = _user(10)
    state.users_by_id[20] = _user(20)
    state.role_ids_by_user_id[10] = {_VISIBLE_ROLE_ID}
    state.role_ids_by_user_id[20] = {_VISIBLE_ROLE_ID}
    state.scores_by_id[1] = _score(score_id=1, user_id=10, score=999)
    state.beatmap_performance_bests_by_id[1] = _best(
        row_id=1,
        user_id=10,
        beatmap_id=100,
        pp=Decimal("999"),
        accuracy=1.0,
    )
    state.current_user_stats_by_scope[(10, Ruleset.OSU.value, Playstyle.VANILLA.value)] = (
        UserStatsProjection(
            scope=UserStatsScope(
                user_id=10,
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
            ),
            pp=Decimal("123.456"),
            accuracy=0.987,
            play_count=7,
            ranked_score=700,
            total_score=900,
            max_combo=321,
            play_time_seconds=456,
            hit_totals=UserStatsHitTotals(count_300=10, count_100=2, count_miss=1),
        )
    )
    state.current_user_stats_by_scope[(20, Ruleset.OSU.value, Playstyle.VANILLA.value)] = (
        UserStatsProjection(
            scope=UserStatsScope(
                user_id=20,
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
            ),
            pp=Decimal("200"),
            accuracy=1.0,
        )
    )
    factory.commit_state(state)
    repository = InMemoryUserStatsQueryRepository(factory)

    result = await repository.read_current_stats_sources((10,))

    source = result.users[0]
    assert source.pp == Decimal("123.456")
    assert source.accuracy == 0.987
    assert source.play_count == 7
    assert source.ranked_score == 700
    assert source.total_score == 900
    assert source.max_combo == 321
    assert source.play_time_seconds == 456
    assert source.hit_totals == UserStatsHitTotals(count_300=10, count_100=2, count_miss=1)
    assert source.best_performances == ()
    assert [(rank.user_id, rank.pp) for rank in result.rank_inputs] == [
        (10, Decimal("123.456")),
        (20, Decimal("200")),
    ]


@pytest.mark.asyncio
async def test_missing_play_time_stays_unavailable_when_all_scores_are_missing_it() -> None:
    """全scoreにplay timeがない場合は統計値を0へ補完しない契約を検証する.

    play_time_secondsがNoneのscoreだけを保存し, sourceのplay timeもNoneのまま返ることを確認する.

    Returns:
        None: unavailable play timeの表現を検証して完了し, 呼び出し側へ値を返さない.
    """
    factory = _factory()
    state = factory.snapshot()
    _seed_visible_role(state)
    state.users_by_id[10] = _user(10)
    state.role_ids_by_user_id[10] = {_VISIBLE_ROLE_ID}
    state.scores_by_id[1] = _score(score_id=1, play_time_seconds=None)
    factory.commit_state(state)
    repository = InMemoryUserStatsQueryRepository(factory)

    result = await repository.read_current_stats_sources((10,))

    assert result.users[0].play_time_seconds is None


def _factory() -> InMemoryUnitOfWorkFactory:
    """独立したUserStats query fixture stateを持つfactoryを構築する.

    Returns:
        InMemoryUnitOfWorkFactory: testごとにsnapshotをcommitできるmemory factory.
    """
    return InMemoryUnitOfWorkFactory(InMemoryCommandRepositoryState())


def _seed_visible_role(state: InMemoryCommandRepositoryState) -> None:
    """Rank inputに含めるvisible roleをfixture stateへ保存する.

    Args:
        state (InMemoryCommandRepositoryState): role mapを更新するmutable snapshot.

    Returns:
        None: unrestricted permissionを持つroleを保存して完了し, 呼び出し側へ値を返さない.
    """
    state.roles_by_id[_VISIBLE_ROLE_ID] = Role(
        id=_VISIBLE_ROLE_ID,
        name="Visible",
        permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
        position=1,
    )


def _seed_hidden_role(state: InMemoryCommandRepositoryState) -> None:
    """Rank inputから除くhidden roleをfixture stateへ保存する.

    Args:
        state (InMemoryCommandRepositoryState): role mapを更新するmutable snapshot.

    Returns:
        None: unrestricted permissionを持たないroleを保存して完了し, 呼び出し側へ値を返さない.
    """
    state.roles_by_id[_HIDDEN_ROLE_ID] = Role(
        id=_HIDDEN_ROLE_ID,
        name="Hidden",
        permissions=Privileges.NORMAL,
        position=0,
    )


def _user(user_id: int) -> User:
    """指定IDを持つUserStats source用User fixtureを構築する.

    Args:
        user_id (int): user名とIDに使うuser識別子.

    Returns:
        User: 固定日時とJP countryを持つuser.
    """
    return User(
        id=user_id,
        username=f"user{user_id}",
        safe_username=f"user{user_id}",
        email=f"user{user_id}@example.test",
        password_hash="hash",
        country="JP",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _score(
    *,
    score_id: int,
    score: int = 100,
    max_combo: int = 400,
    user_id: int = 10,
    mods: ModCombination | None = None,
    passed: bool = True,
    leaderboard_eligible_at_submission: bool = True,
    play_time_seconds: int | None = 10,
    ruleset: Ruleset = Ruleset.OSU,
    playstyle: Playstyle = Playstyle.VANILLA,
) -> Score:
    """UserStats source集計用の保存済みScore fixtureを構築する.

    Args:
        score_id (int): state mapで使うscore ID.
        score (int): total scoreとranked scoreに使う得点.
        max_combo (int): sourceが返す最大combo.
        user_id (int): scoreを提出したuser ID.
        mods (ModCombination | None): playstyle filterを検証するmod組み合わせ. Noneならmodなし.
        passed (bool): pass countとranked scoreに影響する成否.
        leaderboard_eligible_at_submission (bool): ranked score対象かを表すsubmission時flag.
        play_time_seconds (int | None): play time集計に使う秒数. Noneなら利用不可.
        ruleset (Ruleset): source filterに使うruleset.
        playstyle (Playstyle): source filterに使うplaystyle.

    Returns:
        Score: 指定した集計条件を持つ保存済みscore.
    """
    return Score(
        id=score_id,
        user_id=user_id,
        beatmap_id=100,
        beatmap_checksum="a" * 32,
        online_checksum=f"{score_id:032x}",
        ruleset=ruleset,
        playstyle=playstyle,
        mods=mods or ModCombination.none(),
        n300=300,
        n100=20,
        n50=5,
        geki=0,
        katu=0,
        miss=0,
        score=score,
        max_combo=max_combo,
        accuracy=0.98,
        grade=Grade.A,
        passed=passed,
        perfect=False,
        client_version="b20250101",
        submitted_at=_NOW + timedelta(seconds=score_id),
        beatmap_status_at_submission=BeatmapRankStatus.RANKED,
        leaderboard_eligible_at_submission=leaderboard_eligible_at_submission,
        play_time_seconds=play_time_seconds,
    )


def _best(
    *,
    row_id: int,
    user_id: int,
    beatmap_id: int,
    pp: Decimal,
    accuracy: float,
    ruleset: Ruleset = Ruleset.OSU,
    playstyle: Playstyle = Playstyle.VANILLA,
) -> BeatmapPerformanceBest:
    """UserStats rank input用のBeatmapPerformanceBest fixtureを構築する.

    Args:
        row_id (int): projection rowと関連scoreのID.
        user_id (int): performance bestを所有するuser ID.
        beatmap_id (int): bestが対象とするbeatmap ID.
        pp (Decimal): rank inputに使うperformance point.
        accuracy (float): performance bestのaccuracy.
        ruleset (Ruleset): bestを絞り込むruleset.
        playstyle (Playstyle): bestを絞り込むplaystyle.

    Returns:
        BeatmapPerformanceBest: 指定scopeとperformance値を持つbest projection.
    """
    return BeatmapPerformanceBest(
        id=row_id,
        scope=BeatmapPerformanceBestScope(
            user_id=user_id,
            beatmap_id=beatmap_id,
            ruleset=ruleset,
            playstyle=playstyle,
        ),
        score_id=row_id,
        performance_calculation_id=row_id,
        pp=pp,
        accuracy=accuracy,
        score=1_000_000 - row_id,
        submitted_at=_NOW + timedelta(seconds=row_id),
    )
