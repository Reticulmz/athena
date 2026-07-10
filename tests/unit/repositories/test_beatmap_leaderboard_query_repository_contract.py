"""Query repository contract tests for Beatmap Leaderboard projections."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSourceVerification,
)
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.users import User
from osu_server.domain.scores.leaderboards import ALL_MODS_FILTER_KEY, ScoreRankKey
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculation,
    PerformanceCalculationState,
)
from osu_server.domain.scores.personal_best import (
    LeaderboardCategory,
    PersonalBest,
    PersonalBestScope,
)
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBest,
    BeatmapLeaderboardUserBestScope,
)
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    LeaderboardReadScope,
)
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.beatmap_leaderboards import (
    InMemoryBeatmapLeaderboardQueryRepository,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

_NOW = datetime(2026, 6, 18, 0, 0, 0, tzinfo=UTC)
_BEATMAP_ID = 75
_CURRENT_CHECKSUM = "a" * 32
_OLD_CHECKSUM = "b" * 32
_NEW_CHECKSUM = "c" * 32
_VISIBLE_ROLE_ID = 1


async def test_top_rows_are_limited_to_50_and_use_projection_ordering() -> None:
    factory = _factory()
    state = factory.snapshot()
    _seed_beatmap(state)
    _seed_visible_role(state)

    _seed_leaderboard_score(
        state,
        score_id=1,
        user_id=1,
        score=1_000_000,
        submitted_at=_NOW + timedelta(seconds=3),
    )
    _seed_leaderboard_score(
        state,
        score_id=2,
        user_id=2,
        score=2_000_000,
        submitted_at=_NOW + timedelta(seconds=20),
    )
    _seed_leaderboard_score(
        state,
        score_id=3,
        user_id=3,
        score=2_000_000,
        submitted_at=_NOW + timedelta(seconds=10),
    )
    _seed_leaderboard_score(
        state,
        score_id=4,
        user_id=4,
        score=2_000_000,
        submitted_at=_NOW + timedelta(seconds=10),
    )
    for score_id in range(5, 61):
        _seed_leaderboard_score(
            state,
            score_id=score_id,
            user_id=score_id,
            score=1_000_000 - score_id,
            submitted_at=_NOW + timedelta(seconds=score_id),
        )
    factory.commit_state(state)
    repository = InMemoryBeatmapLeaderboardQueryRepository(factory)

    rows = await repository.list_top_rows(_scope(), limit=100)

    assert len(rows) == 50
    assert [row.score_id for row in rows[:4]] == [3, 4, 2, 1]
    assert [row.rank for row in rows[:4]] == [1, 2, 3, 4]
    assert 60 not in {row.score_id for row in rows}


async def test_personal_best_rank_can_be_outside_top_50() -> None:
    factory = _factory()
    state = factory.snapshot()
    _seed_beatmap(state)
    _seed_visible_role(state)
    viewer_user_id = 100

    for score_id in range(1, 52):
        _seed_leaderboard_score(
            state,
            score_id=score_id,
            user_id=score_id,
            score=2_000_000 - score_id,
            submitted_at=_NOW + timedelta(seconds=score_id),
        )
    _seed_leaderboard_score(
        state,
        score_id=100,
        user_id=viewer_user_id,
        score=1_000_000,
        submitted_at=_NOW + timedelta(minutes=1),
    )
    factory.commit_state(state)
    repository = InMemoryBeatmapLeaderboardQueryRepository(factory)

    rows = await repository.list_top_rows(_scope(), limit=50)
    personal_best = await repository.get_personal_best(
        _scope(),
        viewer_user_id=viewer_user_id,
    )

    assert len(rows) == 50
    assert viewer_user_id not in {row.user_id for row in rows}
    assert personal_best is not None
    assert personal_best.score_id == 100
    assert personal_best.rank == 52


async def test_country_and_friends_are_read_time_filters_over_all_mods_scope() -> None:
    factory = _factory()
    state = factory.snapshot()
    _seed_beatmap(state)
    _seed_visible_role(state)
    _seed_leaderboard_score(state, score_id=10, user_id=10, country="JP", score=900_000)
    _seed_leaderboard_score(state, score_id=11, user_id=11, country="US", score=950_000)
    _seed_leaderboard_score(state, score_id=12, user_id=12, country="JP", score=925_000)
    factory.commit_state(state)
    repository = InMemoryBeatmapLeaderboardQueryRepository(factory)

    country_rows = await repository.list_top_rows(
        _scope(
            category=LeaderboardCategory.COUNTRY,
            mod_filter_key=int(Mod.DOUBLE_TIME),
            country="JP",
        ),
        limit=50,
    )
    friends_rows = await repository.list_top_rows(
        _scope(
            category=LeaderboardCategory.FRIENDS,
            mod_filter_key=int(Mod.DOUBLE_TIME),
            eligible_user_ids=(10, 11),
        ),
        limit=50,
    )

    assert [row.user_id for row in country_rows] == [12, 10]
    assert [row.user_id for row in friends_rows] == [11, 10]

    state = factory.snapshot()
    state.users_by_id[11] = replace(state.users_by_id[11], country="JP")
    factory.commit_state(state)

    country_rows_after_country_change = await repository.list_top_rows(
        _scope(
            category=LeaderboardCategory.COUNTRY,
            mod_filter_key=int(Mod.DOUBLE_TIME),
            country="JP",
        ),
        limit=50,
    )

    assert [row.user_id for row in country_rows_after_country_change] == [11, 12, 10]


async def test_selected_mods_use_mod_filter_key_and_preserve_displayed_mods() -> None:
    factory = _factory()
    state = factory.snapshot()
    _seed_beatmap(state)
    _seed_visible_role(state)
    _seed_leaderboard_score(
        state,
        score_id=20,
        user_id=20,
        score=900_000,
        mod_filter_key=ALL_MODS_FILTER_KEY,
        mods=ModCombination.from_bitmask(int(Mod.NIGHTCORE)),
    )
    _seed_leaderboard_score(
        state,
        score_id=21,
        user_id=21,
        score=950_000,
        mod_filter_key=int(Mod.DOUBLE_TIME),
        mods=ModCombination.from_bitmask(int(Mod.NIGHTCORE)),
    )
    factory.commit_state(state)
    repository = InMemoryBeatmapLeaderboardQueryRepository(factory)

    selected_rows = await repository.list_top_rows(
        _scope(
            category=LeaderboardCategory.SELECTED_MODS,
            mod_filter_key=int(Mod.DOUBLE_TIME),
        ),
        limit=50,
    )

    assert [row.score_id for row in selected_rows] == [21]
    assert selected_rows[0].displayed_mods == ModCombination.from_bitmask(int(Mod.NIGHTCORE))


async def test_owner_visibility_filters_rows_and_personal_best_at_read_time() -> None:
    factory = _factory()
    state = factory.snapshot()
    _seed_beatmap(state)
    _seed_visible_role(state)
    hidden_user_id = 30
    visible_user_id = 31
    _seed_leaderboard_score(
        state,
        score_id=30,
        user_id=hidden_user_id,
        score=2_000_000,
        visible=False,
    )
    _seed_leaderboard_score(
        state,
        score_id=31,
        user_id=visible_user_id,
        score=1_000_000,
    )
    factory.commit_state(state)
    repository = InMemoryBeatmapLeaderboardQueryRepository(factory)

    rows = await repository.list_top_rows(_scope(), limit=50)
    hidden_personal_best = await repository.get_personal_best(
        _scope(),
        viewer_user_id=hidden_user_id,
    )

    assert [row.user_id for row in rows] == [visible_user_id]
    assert hidden_personal_best is None

    state = factory.snapshot()
    state.role_ids_by_user_id[hidden_user_id] = {_VISIBLE_ROLE_ID}
    factory.commit_state(state)

    visible_again_rows = await repository.list_top_rows(_scope(), limit=50)
    visible_again_personal_best = await repository.get_personal_best(
        _scope(),
        viewer_user_id=hidden_user_id,
    )

    assert [row.user_id for row in visible_again_rows] == [hidden_user_id, visible_user_id]
    assert visible_again_personal_best is not None
    assert visible_again_personal_best.rank == 1


async def test_current_filters_exclude_stale_or_ineligible_projection_rows() -> None:
    factory = _factory()
    state = factory.snapshot()
    _seed_beatmap(state)
    _seed_visible_role(state)
    _seed_leaderboard_score(state, score_id=40, user_id=40, score=1_000_000)
    _seed_leaderboard_score(state, score_id=41, user_id=41, score=2_000_000, passed=False)
    _seed_leaderboard_score(
        state,
        score_id=42,
        user_id=42,
        score=3_000_000,
        leaderboard_eligible_at_submission=False,
    )
    _seed_leaderboard_score(
        state,
        score_id=43,
        user_id=43,
        score=4_000_000,
        beatmap_checksum=_OLD_CHECKSUM,
    )
    factory.commit_state(state)
    repository = InMemoryBeatmapLeaderboardQueryRepository(factory)

    rows = await repository.list_top_rows(_scope(), limit=50)
    valid_personal_best = await repository.get_personal_best(_scope(), viewer_user_id=40)
    ineligible_personal_best = await repository.get_personal_best(_scope(), viewer_user_id=42)

    assert [row.score_id for row in rows] == [40]
    assert valid_personal_best is not None
    assert valid_personal_best.score_id == 40
    assert ineligible_personal_best is None

    state = factory.snapshot()
    state.beatmaps_by_id[_BEATMAP_ID] = replace(
        state.beatmaps_by_id[_BEATMAP_ID],
        official_status=BeatmapRankStatus.PENDING,
    )
    factory.commit_state(state)

    pending_rows = await repository.list_top_rows(_scope(), limit=50)
    pending_personal_best = await repository.get_personal_best(_scope(), viewer_user_id=40)

    assert pending_rows == ()
    assert pending_personal_best is None

    state = factory.snapshot()
    state.beatmaps_by_id[_BEATMAP_ID] = replace(
        state.beatmaps_by_id[_BEATMAP_ID],
        checksum_md5=_NEW_CHECKSUM,
        official_status=BeatmapRankStatus.RANKED,
    )
    factory.commit_state(state)

    checksum_changed_rows = await repository.list_top_rows(
        _scope(beatmap_checksum=_NEW_CHECKSUM),
        limit=50,
    )
    checksum_changed_personal_best = await repository.get_personal_best(
        _scope(beatmap_checksum=_NEW_CHECKSUM),
        viewer_user_id=40,
    )

    assert checksum_changed_rows == ()
    assert checksum_changed_personal_best is None


async def test_current_pp_is_display_enrichment_for_ranked_approved_rows_only() -> None:
    pp_value = Decimal("250.125000")
    for status, expected_pp in (
        (BeatmapRankStatus.RANKED, pp_value),
        (BeatmapRankStatus.APPROVED, pp_value),
        (BeatmapRankStatus.LOVED, None),
        (BeatmapRankStatus.QUALIFIED, None),
    ):
        factory = _factory()
        state = factory.snapshot()
        _seed_beatmap(state, status=status)
        _seed_visible_role(state)
        _seed_leaderboard_score(state, score_id=50, user_id=50, score=2_000_000)
        _seed_leaderboard_score(state, score_id=51, user_id=51, score=1_000_000)
        _seed_current_performance_calculation(
            state,
            calculation_id=1,
            score_id=51,
            pp=pp_value,
        )
        factory.commit_state(state)
        repository = InMemoryBeatmapLeaderboardQueryRepository(factory)

        rows = await repository.list_top_rows(_scope(), limit=50)
        personal_best = await repository.get_personal_best(_scope(), viewer_user_id=51)

        assert [row.score_id for row in rows] == [50, 51]
        assert [row.rank for row in rows] == [1, 2]
        assert [row.pp for row in rows] == [None, expected_pp]
        assert personal_best is not None
        assert personal_best.rank == 2
        assert personal_best.pp == expected_pp


async def test_beatmap_leaderboard_personal_best_ignores_pp_priority_projection() -> None:
    factory = _factory()
    state = factory.snapshot()
    _seed_beatmap(state)
    _seed_visible_role(state)
    viewer_user_id = 60
    leaderboard_score_id = 60
    pp_priority_score_id = 61
    _seed_leaderboard_score(
        state,
        score_id=leaderboard_score_id,
        user_id=viewer_user_id,
        score=1_000_000,
    )
    state.scores_by_id[pp_priority_score_id] = _score(
        score_id=pp_priority_score_id,
        user_id=viewer_user_id,
        score=900_000,
        submitted_at=_NOW + timedelta(seconds=1),
        mods=ModCombination.none(),
        beatmap_checksum=_CURRENT_CHECKSUM,
        passed=True,
    )
    state.score_leaderboard_eligibility_by_id[pp_priority_score_id] = True
    # Retired or future stats-owned representatives must not drive Beatmap Leaderboard PB.
    state.personal_bests_by_id[1] = PersonalBest(
        id=1,
        scope=PersonalBestScope(
            user_id=viewer_user_id,
            beatmap_id=_BEATMAP_ID,
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
            category=LeaderboardCategory.GLOBAL,
        ),
        score_id=pp_priority_score_id,
        ranking_value=2_000,
    )
    state.personal_best_id_by_scope[
        (
            viewer_user_id,
            _BEATMAP_ID,
            Ruleset.OSU.value,
            Playstyle.VANILLA.value,
            LeaderboardCategory.GLOBAL.value,
        )
    ] = 1
    _seed_current_performance_calculation(
        state,
        calculation_id=1,
        score_id=pp_priority_score_id,
        pp=Decimal("900.000000"),
    )
    factory.commit_state(state)
    repository = InMemoryBeatmapLeaderboardQueryRepository(factory)

    rows = await repository.list_top_rows(_scope(), limit=50)
    personal_best = await repository.get_personal_best(_scope(), viewer_user_id=viewer_user_id)

    assert [row.score_id for row in rows] == [leaderboard_score_id]
    assert personal_best is not None
    assert personal_best.score_id == leaderboard_score_id
    assert personal_best.pp is None


def _factory() -> InMemoryUnitOfWorkFactory:
    return InMemoryUnitOfWorkFactory(InMemoryCommandRepositoryState())


def _scope(
    *,
    category: LeaderboardCategory = LeaderboardCategory.GLOBAL,
    beatmap_checksum: str = _CURRENT_CHECKSUM,
    mod_filter_key: int = ALL_MODS_FILTER_KEY,
    country: str | None = None,
    eligible_user_ids: tuple[int, ...] | None = None,
) -> LeaderboardReadScope:
    return LeaderboardReadScope(
        beatmap_id=_BEATMAP_ID,
        beatmap_checksum=beatmap_checksum,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        category=category,
        mod_filter_key=mod_filter_key,
        country=country,
        eligible_user_ids=eligible_user_ids,
    )


def _seed_visible_role(state: InMemoryCommandRepositoryState) -> None:
    state.roles_by_id[_VISIBLE_ROLE_ID] = Role(
        id=_VISIBLE_ROLE_ID,
        name="Visible",
        permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
        position=1,
    )


def _seed_beatmap(
    state: InMemoryCommandRepositoryState,
    *,
    checksum_md5: str = _CURRENT_CHECKSUM,
    status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
) -> None:
    state.beatmaps_by_id[_BEATMAP_ID] = Beatmap(
        id=_BEATMAP_ID,
        beatmapset_id=5,
        checksum_md5=checksum_md5,
        mode="osu",
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
        official_status=status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.AVAILABLE,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=None,
    )
    state.beatmap_id_by_checksum[checksum_md5] = _BEATMAP_ID


def _seed_leaderboard_score(
    state: InMemoryCommandRepositoryState,
    *,
    score_id: int,
    user_id: int,
    score: int,
    submitted_at: datetime = _NOW,
    country: str = "JP",
    visible: bool = True,
    mod_filter_key: int = ALL_MODS_FILTER_KEY,
    mods: ModCombination | None = None,
    beatmap_checksum: str = _CURRENT_CHECKSUM,
    passed: bool = True,
    leaderboard_eligible_at_submission: bool = True,
) -> None:
    state.users_by_id[user_id] = _user(user_id=user_id, country=country)
    source_mods = mods or ModCombination.none()
    if visible:
        state.role_ids_by_user_id[user_id] = {_VISIBLE_ROLE_ID}
    state.scores_by_id[score_id] = _score(
        score_id=score_id,
        user_id=user_id,
        score=score,
        submitted_at=submitted_at,
        mods=source_mods,
        beatmap_checksum=beatmap_checksum,
        passed=passed,
    )
    state.score_leaderboard_eligibility_by_id[score_id] = leaderboard_eligible_at_submission
    state.beatmap_leaderboard_user_bests_by_id[score_id] = BeatmapLeaderboardUserBest(
        id=score_id,
        scope=BeatmapLeaderboardUserBestScope(
            beatmap_id=_BEATMAP_ID,
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
            user_id=user_id,
            mod_filter_key=mod_filter_key,
        ),
        score_id=score_id,
        rank_key=ScoreRankKey(score=score, submitted_at=submitted_at, score_id=score_id),
    )
    state.beatmap_leaderboard_user_best_id_by_scope[
        (_BEATMAP_ID, Ruleset.OSU.value, Playstyle.VANILLA.value, user_id, mod_filter_key)
    ] = score_id


def _seed_current_performance_calculation(
    state: InMemoryCommandRepositoryState,
    *,
    calculation_id: int,
    score_id: int,
    pp: Decimal,
) -> None:
    state.performance_calculations_by_id[calculation_id] = PerformanceCalculation(
        id=calculation_id,
        score_id=score_id,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
        pp=pp,
        star_rating=Decimal("5.43210"),
        calculator_name="rosu-pp-py",
        calculator_version="4.0.2",
        formula_profile=FormulaProfile.VANILLA_RANKED,
        beatmap_file_attachment_id=55,
        beatmap_file_checksum_md5=_CURRENT_CHECKSUM,
        unavailable_reason=None,
        calculated_at=_NOW,
    )
    state.current_performance_calculation_id_by_score_id[score_id] = calculation_id


def _user(*, user_id: int, country: str) -> User:
    username = f"User{user_id}"
    safe_username = username.lower()
    return User(
        id=user_id,
        username=username,
        safe_username=safe_username,
        email=f"{safe_username}@example.com",
        password_hash="hash",
        country=country,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _score(
    *,
    score_id: int,
    user_id: int,
    score: int,
    submitted_at: datetime,
    mods: ModCombination,
    beatmap_checksum: str,
    passed: bool,
) -> Score:
    return Score(
        id=score_id,
        user_id=user_id,
        beatmap_id=_BEATMAP_ID,
        beatmap_checksum=beatmap_checksum,
        online_checksum=f"{score_id:032x}",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=mods,
        n300=300,
        n100=10,
        n50=1,
        geki=50,
        katu=5,
        miss=0,
        score=score,
        max_combo=1_234,
        accuracy=98.76,
        grade=Grade.S,
        passed=passed,
        perfect=True,
        client_version="b20260618",
        submitted_at=submitted_at,
        beatmap_status_at_submission="ranked" if passed else None,
    )
