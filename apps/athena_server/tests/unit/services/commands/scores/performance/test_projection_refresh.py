"""performance best projectionのrefresh/rebuild contractを検証するtest module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculationState,
)
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.domain.scores.user_stats import UserStatsProjection, UserStatsScope
from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
    BeatmapPerformanceBestScope,
    UpsertBeatmapPerformanceBest,
)
from osu_server.repositories.interfaces.commands.score_performance import (
    CompleteScorePerformanceCalculation,
    CreateScorePerformanceCalculation,
    MarkScorePerformanceCalculationUnavailable,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.scores.performance.projection_refresh import (
    RebuildPerformanceBestProjectionCommand,
    RebuildPerformanceBestProjectionOutcome,
    RebuildPerformanceBestProjectionUseCase,
    RefreshPerformanceBestCommand,
    RefreshPerformanceBestOutcome,
    RefreshPerformanceBestUseCase,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_NOW = datetime(2026, 6, 28, 0, 0, 0, tzinfo=UTC)
_CALCULATOR_NAME = "rosu-pp-py"
_CALCULATOR_VERSION = "4.0.2"
_RECALCULATOR_VERSION = "4.1.0"


@pytest.mark.asyncio
async def test_refresh_upserts_eligible_score_with_completed_current_pp() -> None:
    """Eligible scoreのcompleted current PPをperformance bestへupsertするrefresh契約を検証する.

    ranked vanilla scoreとcompleted calculationを保存してrefreshし scoreとcalculationとPPを保持した
    projectionが保存されることを確認する.

    Returns:
        None: refresh outcomeと返却projectionと永続化されたbest rowを検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    score_id = await _persist_score(factory, _score(accuracy=0.9876, score=987_654))
    calculation_id = await _complete_current_performance(
        factory,
        score_id=score_id,
        pp=Decimal("123.456"),
    )
    use_case = RefreshPerformanceBestUseCase(unit_of_work_factory=factory)

    result = await use_case.execute(RefreshPerformanceBestCommand(score_id=score_id))

    assert result.outcome is RefreshPerformanceBestOutcome.REFRESHED
    assert result.projection is not None
    assert result.projection.score_id == score_id
    assert result.projection.performance_calculation_id == calculation_id
    assert result.projection.pp == Decimal("123.456")
    assert result.projection.accuracy == 0.9876
    assert result.projection.score == 987_654

    async with factory() as uow:
        persisted = await uow.beatmap_performance_bests.get_best(
            _scope(user_id=1000, beatmap_id=1)
        )
        current = await uow.score_performance.get_current_for_score(score_id)

    assert persisted == result.projection
    assert current is not None
    assert current.id == calculation_id
    assert current.state is PerformanceCalculationState.COMPLETED
    assert current.pp == Decimal("123.456")


@pytest.mark.asyncio
async def test_refresh_skips_pending_performance_without_projection_mutation() -> None:
    """Pending performanceを持つscoreがprojectionを変更せずskipされるrefresh契約を検証する.

    queued calculationを関連付けたeligible scoreをrefreshする.
    current PP不足のoutcomeとprojection未作成を確認する.

    Returns:
        None: missing current PP outcomeとqueued calculationとbest row不在を検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    score_id = await _persist_score(factory, _score())
    calculation_id = await _create_pending_performance(factory, score_id=score_id)
    use_case = RefreshPerformanceBestUseCase(unit_of_work_factory=factory)

    result = await use_case.execute(RefreshPerformanceBestCommand(score_id=score_id))

    assert result.outcome is RefreshPerformanceBestOutcome.MISSING_CURRENT_PP
    assert result.projection is None
    async with factory() as uow:
        assert await uow.beatmap_performance_bests.get_best(_scope()) is None
        current = await uow.score_performance.get_current_for_score(score_id)

    assert current is not None
    assert current.id == calculation_id
    assert current.state is PerformanceCalculationState.QUEUED
    assert current.pp is None


@pytest.mark.asyncio
async def test_refresh_skips_unavailable_performance_without_projection_mutation() -> None:
    """Unavailable performanceを持つscoreがprojectionを変更せずskipされるrefresh契約を検証する.

    unavailable calculationを関連付けたeligible scoreをrefreshする.
    unavailable outcomeとprojection未作成を確認する.

    Returns:
        None: unavailable outcomeとreasonとbest row不在を検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    score_id = await _persist_score(factory, _score())
    calculation_id = await _create_unavailable_performance(factory, score_id=score_id)
    use_case = RefreshPerformanceBestUseCase(unit_of_work_factory=factory)

    result = await use_case.execute(RefreshPerformanceBestCommand(score_id=score_id))

    assert result.outcome is RefreshPerformanceBestOutcome.PERFORMANCE_UNAVAILABLE
    assert result.projection is None
    async with factory() as uow:
        assert await uow.beatmap_performance_bests.get_best(_scope()) is None
        current = await uow.score_performance.get_current_for_score(score_id)

    assert current is not None
    assert current.id == calculation_id
    assert current.state is PerformanceCalculationState.UNAVAILABLE
    assert current.unavailable_reason == "calculator_input_invalid"


@pytest.mark.asyncio
async def test_refresh_rebuilds_user_slice_when_current_pp_disappears() -> None:
    """Current PP消失時にrefreshがuser sliceとcurrent statsを再構築する契約を検証する.

    2つの既存projectionの一方をunavailable replacementへ置き換えてrefreshし 失効したbest rowを
    削除し残ったscoreからcurrent statsを再計算することを確認する.

    Returns:
        None: unavailable outcomeと保持されるprojection, 削除されるprojection, statsを
            検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    kept_score_id = await _persist_score(
        factory,
        _score(beatmap_id=1, score=900_000, submitted_at=_NOW),
    )
    stale_score_id = await _persist_score(
        factory,
        _score(beatmap_id=2, score=1_000_000, submitted_at=_NOW + timedelta(seconds=1)),
    )
    kept_calculation_id = await _complete_current_performance(
        factory,
        score_id=kept_score_id,
        pp=Decimal("125"),
    )
    stale_calculation_id = await _complete_current_performance(
        factory,
        score_id=stale_score_id,
        pp=Decimal("200"),
    )
    await _seed_projection(
        factory,
        _upsert(
            scope=_scope(beatmap_id=1),
            score_id=kept_score_id,
            calculation_id=kept_calculation_id,
            pp=Decimal("125"),
            submitted_at=_NOW,
        ),
    )
    await _seed_projection(
        factory,
        _upsert(
            scope=_scope(beatmap_id=2),
            score_id=stale_score_id,
            calculation_id=stale_calculation_id,
            pp=Decimal("200"),
            submitted_at=_NOW + timedelta(seconds=1),
        ),
    )
    _ = await _replace_current_performance_as_unavailable(
        factory,
        score_id=stale_score_id,
    )
    use_case = RefreshPerformanceBestUseCase(unit_of_work_factory=factory)

    result = await use_case.execute(RefreshPerformanceBestCommand(score_id=stale_score_id))

    assert result.outcome is RefreshPerformanceBestOutcome.PERFORMANCE_UNAVAILABLE
    assert result.projection is None
    async with factory() as uow:
        kept = await uow.beatmap_performance_bests.get_best(_scope(beatmap_id=1))
        removed = await uow.beatmap_performance_bests.get_best(_scope(beatmap_id=2))
        current_stats = await uow.current_user_stats.get(
            UserStatsScope(
                user_id=1000,
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
            )
        )

    assert kept is not None
    assert kept.score_id == kept_score_id
    assert kept.pp == Decimal("125")
    assert removed is None
    assert current_stats is not None
    assert current_stats.pp == Decimal("125")
    assert current_stats.play_count == 2


@pytest.mark.asyncio
async def test_refresh_non_best_score_does_not_rebuild_current_stats() -> None:
    """non-best scoreのrefreshが既存current statsを再構築しない契約を検証する.

    より高い既存best rowと固定current statsを保存してから低いPPのscoreをrefreshする.
    best rowを維持してseeded statsを変更しないことを確認する.

    Returns:
        None: refresh outcomeと維持されるbest rowと変更されないcurrent statsを検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    best_score_id = await _persist_score(
        factory,
        _score(score=950_000, submitted_at=_NOW),
    )
    lower_score_id = await _persist_score(
        factory,
        _score(score=900_000, submitted_at=_NOW + timedelta(seconds=1)),
    )
    best_calculation_id = await _complete_current_performance(
        factory,
        score_id=best_score_id,
        pp=Decimal("200"),
    )
    _ = await _complete_current_performance(
        factory,
        score_id=lower_score_id,
        pp=Decimal("100"),
    )
    await _seed_projection(
        factory,
        _upsert(
            scope=_scope(),
            score_id=best_score_id,
            calculation_id=best_calculation_id,
            pp=Decimal("200"),
            submitted_at=_NOW,
        ),
    )
    await _seed_current_stats(factory, pp=Decimal("999"))
    use_case = RefreshPerformanceBestUseCase(unit_of_work_factory=factory)

    result = await use_case.execute(RefreshPerformanceBestCommand(score_id=lower_score_id))

    assert result.outcome is RefreshPerformanceBestOutcome.REFRESHED
    assert result.projection is not None
    assert result.projection.score_id == best_score_id
    async with factory() as uow:
        best = await uow.beatmap_performance_bests.get_best(_scope())
        current_stats = await uow.current_user_stats.get(
            UserStatsScope(
                user_id=1000,
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
            )
        )

    assert best is not None
    assert best.score_id == best_score_id
    assert current_stats is not None
    assert current_stats.pp == Decimal("999")


@pytest.mark.asyncio
async def test_refresh_skips_relax_play_before_reading_performance() -> None:
    """Relax playがperformanceを参照する前にskipされるrefresh契約を検証する.

    relax modを持つscoreをcalculationなしでrefreshする.
    playstyle out of scopeのskip reasonとprojection未作成を確認する.

    Returns:
        None: ineligible score outcomeとskip reasonとbest row不在を検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    score_id = await _persist_score(
        factory,
        _score(mods=ModCombination(Mod.RELAX)),
    )
    use_case = RefreshPerformanceBestUseCase(unit_of_work_factory=factory)

    result = await use_case.execute(RefreshPerformanceBestCommand(score_id=score_id))

    assert result.outcome is RefreshPerformanceBestOutcome.SKIPPED_INELIGIBLE_SCORE
    assert result.skip_reason == "playstyle_out_of_scope"
    async with factory() as uow:
        assert await uow.beatmap_performance_bests.get_best(_scope()) is None


@pytest.mark.asyncio
async def test_refresh_skips_leaderboard_ineligible_score() -> None:
    """leaderboard対象外scoreがcompleted performanceを持ってもskipされるrefresh契約を検証する.

    leaderboard eligibilityをfalseにしたscoreへcompleted calculationを保存してrefreshする.
    projectionを作らずcalculationを維持することを確認する.

    Returns:
        None: ineligible score outcome, skip reason, completed calculation, best row不在を
            検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    score_id = await _persist_score(
        factory,
        _score(leaderboard_eligible=False),
    )
    calculation_id = await _complete_current_performance(
        factory,
        score_id=score_id,
        pp=Decimal("123.456"),
    )
    use_case = RefreshPerformanceBestUseCase(unit_of_work_factory=factory)

    result = await use_case.execute(RefreshPerformanceBestCommand(score_id=score_id))

    assert result.outcome is RefreshPerformanceBestOutcome.SKIPPED_INELIGIBLE_SCORE
    assert result.skip_reason == "leaderboard_ineligible"
    assert result.projection is None
    async with factory() as uow:
        assert await uow.beatmap_performance_bests.get_best(_scope()) is None
        current = await uow.score_performance.get_current_for_score(score_id)

    assert current is not None
    assert current.id == calculation_id
    assert current.state is PerformanceCalculationState.COMPLETED


@pytest.mark.asyncio
async def test_rebuild_user_slice_converges_after_recalculation_unavailable_outcome() -> None:
    """User slice rebuildがunavailable recalculation後のbest projectionへ収束する契約を検証する.

    同一userのcompleted calculation群とunavailable replacementを保存してrebuildする.
    highest completed PPだけを投影して失効したbeatmap rowを削除することを確認する.

    Returns:
        None: rebuild countと保持されるhighest projection, 削除されるstale projectionを
            検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    low_score_id = await _persist_score(
        factory,
        _score(score=900_000, accuracy=0.95, submitted_at=_NOW),
    )
    high_score_id = await _persist_score(
        factory,
        _score(score=950_000, accuracy=0.99, submitted_at=_NOW + timedelta(seconds=1)),
    )
    stale_score_id = await _persist_score(
        factory,
        _score(beatmap_id=2, score=1_000_000, submitted_at=_NOW + timedelta(seconds=2)),
    )
    _ = await _complete_current_performance(
        factory,
        score_id=low_score_id,
        pp=Decimal("100"),
    )
    high_calculation_id = await _complete_current_performance(
        factory,
        score_id=high_score_id,
        pp=Decimal("125"),
    )
    stale_calculation_id = await _complete_current_performance(
        factory,
        score_id=stale_score_id,
        pp=Decimal("200"),
    )
    await _seed_projection(
        factory,
        _upsert(
            scope=_scope(user_id=1000, beatmap_id=2),
            score_id=stale_score_id,
            calculation_id=stale_calculation_id,
            pp=Decimal("200"),
            submitted_at=_NOW + timedelta(seconds=2),
        ),
    )
    _ = await _replace_current_performance_as_unavailable(
        factory,
        score_id=stale_score_id,
    )
    use_case = RebuildPerformanceBestProjectionUseCase(unit_of_work_factory=factory)

    result = await use_case.execute(RebuildPerformanceBestProjectionCommand(user_id=1000))

    assert result.outcome is RebuildPerformanceBestProjectionOutcome.REBUILT
    assert result.candidate_count == 3
    assert result.projected_count == 1
    assert result.skip_reasons == {"performance_unavailable": 1}

    async with factory() as uow:
        best = await uow.beatmap_performance_bests.get_best(_scope(user_id=1000, beatmap_id=1))
        removed = await uow.beatmap_performance_bests.get_best(_scope(user_id=1000, beatmap_id=2))

    assert best is not None
    assert best.score_id == high_score_id
    assert best.performance_calculation_id == high_calculation_id
    assert best.pp == Decimal("125")
    assert removed is None


@pytest.mark.asyncio
async def test_rebuild_beatmap_slice_replaces_each_user_scope_and_keeps_other_beatmaps() -> None:
    """Beatmap slice rebuildが全user scopeを置換し他beatmapのprojectionを維持する契約を検証する.

    指定beatmapの2 user scoreと別beatmapの既存projectionを保存してrebuildし 対象2 scopeを投影して
    非対象beatmap rowを残すことを確認する.

    Returns:
        None: rebuild countと対象user scopeのprojectionと維持される別beatmap rowを検証して完了する.
    """
    factory = InMemoryUnitOfWorkFactory()
    first_score_id = await _persist_score(
        factory,
        _score(user_id=1000, beatmap_id=9, score=900_000),
    )
    second_score_id = await _persist_score(
        factory,
        _score(user_id=2000, beatmap_id=9, score=920_000),
    )
    unaffected_score_id = await _persist_score(
        factory,
        _score(user_id=1000, beatmap_id=10, score=800_000),
    )
    first_calculation_id = await _complete_current_performance(
        factory,
        score_id=first_score_id,
        pp=Decimal("100"),
    )
    second_calculation_id = await _complete_current_performance(
        factory,
        score_id=second_score_id,
        pp=Decimal("110"),
    )
    unaffected_calculation_id = await _complete_current_performance(
        factory,
        score_id=unaffected_score_id,
        pp=Decimal("90"),
    )
    unaffected = _upsert(
        scope=_scope(user_id=1000, beatmap_id=10),
        score_id=unaffected_score_id,
        calculation_id=unaffected_calculation_id,
        pp=Decimal("90"),
        submitted_at=_NOW,
    )
    await _seed_projection(factory, unaffected)
    use_case = RebuildPerformanceBestProjectionUseCase(unit_of_work_factory=factory)

    result = await use_case.execute(RebuildPerformanceBestProjectionCommand(beatmap_ids=(9,)))

    assert result.outcome is RebuildPerformanceBestProjectionOutcome.REBUILT
    assert result.candidate_count == 2
    assert result.projected_count == 2
    async with factory() as uow:
        first = await uow.beatmap_performance_bests.get_best(_scope(user_id=1000, beatmap_id=9))
        second = await uow.beatmap_performance_bests.get_best(_scope(user_id=2000, beatmap_id=9))
        other = await uow.beatmap_performance_bests.get_best(_scope(user_id=1000, beatmap_id=10))

    assert first is not None
    assert first.score_id == first_score_id
    assert first.performance_calculation_id == first_calculation_id
    assert second is not None
    assert second.score_id == second_score_id
    assert second.performance_calculation_id == second_calculation_id
    assert other is not None
    assert other.score_id == unaffected_score_id


async def _persist_score(factory: UnitOfWorkFactory, score: Score) -> int:
    """scoreと対応するbeatmapset snapshotをin-memory persistenceへ保存する.

    Args:
        factory (UnitOfWorkFactory): scoreとbeatmap metadataを保存するunit of work factory.
        score (Score): snapshotとともに永続化するtest score.

    Returns:
        int: 保存後に割り当てられたscore ID.
    """
    async with factory() as uow:
        await uow.beatmaps.save_beatmapset_snapshot(_beatmapset_for_score(score))
        created = await uow.scores.create(score)
        await uow.commit()

    assert created.id is not None
    return created.id


def _beatmapset_for_score(score: Score) -> BeatmapSet:
    """scoreのsubmission metadataに一致するbeatmapset snapshotを組み立てる.

    Args:
        score (Score): beatmap IDとsubmission statusを提供するtest score.

    Returns:
        BeatmapSet: scoreのbeatmapを1件含むfresh metadata snapshot.

    Raises:
        AssertionError: scoreにsubmission時のbeatmap statusがない場合.
    """
    official_status = score.beatmap_status_at_submission
    assert official_status is not None
    beatmap = Beatmap(
        id=score.beatmap_id,
        beatmapset_id=score.beatmap_id,
        checksum_md5=score.beatmap_checksum,
        mode=BeatmapMode.OSU,
        version="Test",
        total_length=None,
        hit_length=None,
        max_combo=None,
        bpm=None,
        cs=None,
        od=None,
        ar=None,
        hp=None,
        difficulty_rating=None,
        official_status=official_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=None,
        next_refresh_at=None,
    )
    return BeatmapSet(
        id=score.beatmap_id,
        artist="artist",
        title="title",
        creator="creator",
        artist_unicode=None,
        title_unicode=None,
        official_status=official_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=None,
        next_refresh_at=None,
    )


async def _create_pending_performance(
    factory: UnitOfWorkFactory,
    *,
    score_id: int,
    calculator_version: str = _CALCULATOR_VERSION,
) -> int:
    """score用のqueued performance calculationを用意して識別子を返す.

    Args:
        factory (UnitOfWorkFactory): calculationを保存するunit of work factory.
        score_id (int): calculationを関連付けるscoreの識別子.
        calculator_version (str): calculationへ保存するcalculator version.

    Returns:
        int: queued calculationの永続化済み識別子.
    """
    async with factory() as uow:
        result = await uow.score_performance.create_or_reuse_calculation(
            CreateScorePerformanceCalculation(
                score_id=score_id,
                calculator_name=_CALCULATOR_NAME,
                calculator_version=calculator_version,
                formula_profile=FormulaProfile.VANILLA_RANKED,
                requested_at=_NOW,
            )
        )
        await uow.commit()

    assert result.calculation.id is not None
    return result.calculation.id


async def _complete_current_performance(
    factory: UnitOfWorkFactory,
    *,
    score_id: int,
    pp: Decimal,
    calculator_version: str = _CALCULATOR_VERSION,
) -> int:
    """score用calculationをcompleted current performanceとして確定する.

    Args:
        factory (UnitOfWorkFactory): calculation stateを保存するunit of work factory.
        score_id (int): completed calculationを関連付けるscoreの識別子.
        pp (Decimal): completion resultへ設定するperformance point値.
        calculator_version (str): calculationとcompletion resultへ保存するcalculator version.

    Returns:
        int: completed current calculationの識別子.
    """
    calculation_id = await _create_pending_performance(
        factory,
        score_id=score_id,
        calculator_version=calculator_version,
    )
    async with factory() as uow:
        completed = await uow.score_performance.mark_completed(
            CompleteScorePerformanceCalculation(
                calculation_id=calculation_id,
                pp=pp,
                star_rating=Decimal("5.0"),
                calculator_name=_CALCULATOR_NAME,
                calculator_version=calculator_version,
                formula_profile=FormulaProfile.VANILLA_RANKED,
                beatmap_file_attachment_id=55,
                beatmap_file_checksum_md5="a" * 32,
                calculated_at=_NOW,
            )
        )
        await uow.commit()

    assert completed is not None
    assert completed.id == calculation_id
    return calculation_id


async def _create_unavailable_performance(
    factory: UnitOfWorkFactory,
    *,
    score_id: int,
    calculator_version: str = _CALCULATOR_VERSION,
) -> int:
    """score用calculationをunavailable performanceとして確定する.

    Args:
        factory (UnitOfWorkFactory): calculation stateを保存するunit of work factory.
        score_id (int): unavailable calculationを関連付けるscoreの識別子.
        calculator_version (str): calculationとunavailable resultへ保存するcalculator version.

    Returns:
        int: unavailable calculationの識別子.
    """
    calculation_id = await _create_pending_performance(
        factory,
        score_id=score_id,
        calculator_version=calculator_version,
    )
    async with factory() as uow:
        unavailable = await uow.score_performance.mark_unavailable(
            MarkScorePerformanceCalculationUnavailable(
                calculation_id=calculation_id,
                calculator_name=_CALCULATOR_NAME,
                calculator_version=calculator_version,
                formula_profile=FormulaProfile.VANILLA_RANKED,
                beatmap_file_attachment_id=None,
                beatmap_file_checksum_md5=None,
                reason="calculator_input_invalid",
                calculated_at=_NOW,
            )
        )
        await uow.commit()

    assert unavailable is not None
    assert unavailable.id == calculation_id
    return calculation_id


async def _replace_current_performance_as_unavailable(
    factory: UnitOfWorkFactory,
    *,
    score_id: int,
) -> int:
    """旧calculator provenanceのcurrent performanceをunavailable replacementへ置き換える.

    Args:
        factory (UnitOfWorkFactory): replacement calculationを保存するunit of work factory.
        score_id (int): stale current calculationを持つscoreの識別子.

    Returns:
        int: recalculator versionで作成したunavailable replacementの識別子.
    """
    return await _create_unavailable_performance(
        factory,
        score_id=score_id,
        calculator_version=_RECALCULATOR_VERSION,
    )


async def _seed_projection(
    factory: UnitOfWorkFactory,
    row: UpsertBeatmapPerformanceBest,
) -> None:
    """既存performance best projectionをtest fixtureとして保存する.

    Args:
        factory (UnitOfWorkFactory): projectionを保存するunit of work factory.
        row (UpsertBeatmapPerformanceBest): 保存するbeatmap performance best row.

    Returns:
        None: projectionをupsertしてcommitした後に値を返さず完了する.
    """
    async with factory() as uow:
        _ = await uow.beatmap_performance_bests.upsert_if_better(row)
        await uow.commit()


async def _seed_current_stats(
    factory: UnitOfWorkFactory,
    *,
    pp: Decimal,
) -> None:
    """固定user scopeのcurrent stats projectionをtest fixtureとして保存する.

    Args:
        factory (UnitOfWorkFactory): current statsを保存するunit of work factory.
        pp (Decimal): fixtureへ設定するperformance point値.

    Returns:
        None: current statsを置換してcommitした後に値を返さず完了する.
    """
    async with factory() as uow:
        _ = await uow.current_user_stats.replace(
            UserStatsProjection(
                scope=UserStatsScope(
                    user_id=1000,
                    ruleset=Ruleset.OSU,
                    playstyle=Playstyle.VANILLA,
                ),
                pp=pp,
                accuracy=0.5,
            )
        )
        await uow.commit()


def _score(
    *,
    user_id: int = 1000,
    beatmap_id: int = 1,
    ruleset: Ruleset = Ruleset.OSU,
    playstyle: Playstyle = Playstyle.VANILLA,
    mods: ModCombination | None = None,
    score: int = 1_000_000,
    accuracy: float = 0.98,
    submitted_at: datetime = _NOW,
    passed: bool = True,
    beatmap_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    leaderboard_eligible: bool = True,
) -> Score:
    """Projection refresh条件を制御できる未永続化scoreを組み立てる.

    Args:
        user_id (int): scoreを所有するuserの識別子.
        beatmap_id (int): scoreを関連付けるbeatmapの識別子.
        ruleset (Ruleset): scoreに設定するruleset.
        playstyle (Playstyle): scoreに設定するplaystyle.
        mods (ModCombination | None): scoreに設定するmod. Noneの場合はmodなしを使う.
        score (int): score valueとして保存する値.
        accuracy (float): scoreに設定するaccuracy.
        submitted_at (datetime): score submission時刻.
        passed (bool): scoreをpassedとして扱うか.
        beatmap_status (BeatmapRankStatus): submission時のbeatmap status.
        leaderboard_eligible (bool): scoreをleaderboard対象として扱うか.

    Returns:
        Score: 指定条件とdefault vanilla metadataを持つ未永続化score.
    """
    return Score(
        id=None,
        user_id=user_id,
        beatmap_id=beatmap_id,
        beatmap_checksum=f"{beatmap_id:032x}",
        online_checksum=f"online-{user_id}-{beatmap_id}-{score}-{submitted_at.timestamp()}",
        ruleset=ruleset,
        playstyle=playstyle,
        mods=mods or ModCombination.none(),
        n300=300,
        n100=20,
        n50=5,
        geki=10,
        katu=4,
        miss=0,
        score=score,
        max_combo=500,
        accuracy=accuracy,
        grade=Grade.A,
        passed=passed,
        perfect=False,
        client_version="b20240201",
        submitted_at=submitted_at,
        beatmap_status_at_submission=beatmap_status,
        leaderboard_eligible_at_submission=leaderboard_eligible,
    )


def _scope(
    *,
    user_id: int = 1000,
    beatmap_id: int = 1,
) -> BeatmapPerformanceBestScope:
    """指定userとbeatmap用のvanilla performance best scopeを組み立てる.

    Args:
        user_id (int): scopeに含めるuserの識別子.
        beatmap_id (int): scopeに含めるbeatmapの識別子.

    Returns:
        BeatmapPerformanceBestScope: OSU rulesetとVANILLA playstyleを固定したscope.
    """
    return BeatmapPerformanceBestScope(
        user_id=user_id,
        beatmap_id=beatmap_id,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
    )


def _upsert(
    *,
    scope: BeatmapPerformanceBestScope,
    score_id: int,
    calculation_id: int,
    pp: Decimal,
    submitted_at: datetime,
) -> UpsertBeatmapPerformanceBest:
    """Performance best projectionをseedするupsert commandを組み立てる.

    Args:
        scope (BeatmapPerformanceBestScope): projectionを保存するuserとbeatmapのscope.
        score_id (int): projectionが参照するscoreの識別子.
        calculation_id (int): projectionが参照するperformance calculationの識別子.
        pp (Decimal): projectionへ保存するperformance point値.
        submitted_at (datetime): score submission時刻.

    Returns:
        UpsertBeatmapPerformanceBest: 固定accuracyとscore valueを含むprojection upsert command.
    """
    return UpsertBeatmapPerformanceBest(
        scope=scope,
        score_id=score_id,
        performance_calculation_id=calculation_id,
        pp=pp,
        accuracy=0.98,
        score=1_000_000,
        submitted_at=submitted_at,
    )
