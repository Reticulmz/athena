"""Query repository contract tests for score performance read models."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from osu_server.domain.beatmaps import BeatmapFileAttachment
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.performance import (
    FormulaProfile,
    PerformanceCalculation,
    PerformanceCalculationState,
)
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.queries.score_performance import (
    RecalculationCandidateReason,
    ScorePerformanceCandidateSelection,
)
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.score_performance import (
    InMemoryScorePerformanceQueryRepository,
)
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

_NOW = datetime(2026, 6, 16, 0, 0, 0, tzinfo=UTC)


async def test_current_read_uses_only_current_calculation() -> None:
    factory = _factory_with_state()
    state = factory.snapshot()
    current = _calculation(
        calculation_id=1,
        score_id=10,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
        calculator_version="4.0.2",
    )
    historical = _calculation(
        calculation_id=2,
        score_id=10,
        state=PerformanceCalculationState.SUPERSEDED,
        is_current=False,
        calculator_version="3.0.0",
    )
    state.performance_calculations_by_id[1] = current
    state.performance_calculations_by_id[2] = historical
    state.current_performance_calculation_id_by_score_id[10] = 1
    factory.commit_state(state)

    repository = _repository(factory)

    result = await repository.get_current_for_score(10)

    assert result == current


async def test_candidate_selection_reports_dry_run_counts_and_filters() -> None:
    factory = _factory_with_state()
    _seed_scores(factory)
    state = factory.snapshot()
    state.performance_calculations_by_id[1] = _calculation(
        calculation_id=1,
        score_id=2,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
        calculator_version="3.9.0",
    )
    state.current_performance_calculation_id_by_score_id[2] = 1
    state.performance_calculations_by_id[2] = _calculation(
        calculation_id=2,
        score_id=3,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
        calculator_version="4.0.2",
        formula_profile=FormulaProfile.VANILLA_RANKED,
    )
    state.current_performance_calculation_id_by_score_id[3] = 2
    state.performance_calculations_by_id[3] = _calculation(
        calculation_id=3,
        score_id=4,
        state=PerformanceCalculationState.UNAVAILABLE,
        is_current=True,
        calculator_version="4.0.2",
        unavailable_reason="osu_file_unusable",
    )
    state.current_performance_calculation_id_by_score_id[4] = 3
    state.performance_calculations_by_id[4] = _calculation(
        calculation_id=4,
        score_id=7,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
        calculator_version="4.0.2",
        formula_profile=FormulaProfile.LEGACY_VANILLA_RANKED,
    )
    state.current_performance_calculation_id_by_score_id[7] = 4
    state.performance_calculations_by_id[5] = _calculation(
        calculation_id=5,
        score_id=8,
        state=PerformanceCalculationState.COMPLETED,
        is_current=True,
        calculator_version="4.0.2",
        beatmap_file_attachment_id=90,
        beatmap_file_checksum_md5="9" * 32,
    )
    state.current_performance_calculation_id_by_score_id[8] = 5
    state.attachments_by_key[(100, "current")] = _attachment(
        beatmap_id=100,
        blob_id=91,
        checksum_md5="a" * 32,
    )
    state.attachment_keys_by_beatmap_id[100] = [(100, "current")]
    factory.commit_state(state)

    repository = _repository(factory)

    result = await repository.select_recalculation_candidates(
        ScorePerformanceCandidateSelection(
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
            score_id=None,
            beatmap_id=100,
            user_id=None,
            ruleset=Ruleset.OSU,
            limit=None,
            include_unavailable=True,
        )
    )

    assert [candidate.score_id for candidate in result.candidates] == [1, 2, 4, 7, 8]
    assert result.reason_counts == {
        RecalculationCandidateReason.UNCALCULATED: 1,
        RecalculationCandidateReason.CALCULATOR_VERSION_MISMATCH: 1,
        RecalculationCandidateReason.UNAVAILABLE: 1,
        RecalculationCandidateReason.FORMULA_PROFILE_MISMATCH: 1,
        RecalculationCandidateReason.STALE: 1,
    }


async def test_candidate_selection_applies_limit_and_excludes_unavailable_by_default() -> None:
    factory = _factory_with_state()
    _seed_scores(factory)
    state = factory.snapshot()
    state.performance_calculations_by_id[1] = _calculation(
        calculation_id=1,
        score_id=4,
        state=PerformanceCalculationState.UNAVAILABLE,
        is_current=True,
        unavailable_reason="osu_file_unusable",
    )
    state.current_performance_calculation_id_by_score_id[4] = 1
    factory.commit_state(state)

    repository = _repository(factory)

    result = await repository.select_recalculation_candidates(
        ScorePerformanceCandidateSelection(
            target_calculator_name="rosu-pp-py",
            target_calculator_version="4.0.2",
            target_formula_profile=FormulaProfile.VANILLA_RANKED,
            score_id=None,
            beatmap_id=100,
            user_id=None,
            ruleset=Ruleset.OSU,
            limit=1,
            include_unavailable=False,
        )
    )

    assert [candidate.score_id for candidate in result.candidates] == [1]
    assert result.reason_counts == {RecalculationCandidateReason.UNCALCULATED: 1}


def _factory_with_state() -> InMemoryUnitOfWorkFactory:
    return InMemoryUnitOfWorkFactory(InMemoryCommandRepositoryState())


def _repository(factory: InMemoryUnitOfWorkFactory) -> InMemoryScorePerformanceQueryRepository:
    return InMemoryScorePerformanceQueryRepository(factory)


def _seed_scores(factory: InMemoryUnitOfWorkFactory) -> None:
    state = factory.snapshot()
    scores = (
        _score(score_id=1, user_id=10, beatmap_id=100),
        _score(score_id=2, user_id=10, beatmap_id=100),
        _score(score_id=3, user_id=20, beatmap_id=100),
        _score(score_id=4, user_id=20, beatmap_id=100),
        _score(score_id=5, user_id=20, beatmap_id=100, passed=False),
        _score(score_id=6, user_id=20, beatmap_id=100, beatmap_status="loved"),
        _score(score_id=7, user_id=20, beatmap_id=100),
        _score(score_id=8, user_id=20, beatmap_id=100),
    )
    for score in scores:
        assert score.id is not None
        state.scores_by_id[score.id] = score
    factory.commit_state(state)


def _score(
    *,
    score_id: int,
    user_id: int,
    beatmap_id: int,
    passed: bool = True,
    beatmap_status: str = "ranked",
) -> Score:
    return Score(
        id=score_id,
        user_id=user_id,
        beatmap_id=beatmap_id,
        beatmap_checksum="b" * 32,
        online_checksum=f"{score_id:032x}",
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        mods=ModCombination.none(),
        n300=300,
        n100=10,
        n50=0,
        geki=50,
        katu=5,
        miss=0,
        score=1_000_000,
        max_combo=500,
        accuracy=98.5,
        grade=Grade.S,
        passed=passed,
        perfect=False,
        client_version="b20250101",
        submitted_at=_NOW,
        beatmap_status_at_submission=beatmap_status,
    )


def _calculation(
    *,
    calculation_id: int,
    score_id: int,
    state: PerformanceCalculationState,
    is_current: bool,
    calculator_version: str = "4.0.2",
    formula_profile: FormulaProfile = FormulaProfile.VANILLA_RANKED,
    beatmap_file_attachment_id: int = 55,
    beatmap_file_checksum_md5: str = "a" * 32,
    unavailable_reason: str | None = None,
) -> PerformanceCalculation:
    return PerformanceCalculation(
        id=calculation_id,
        score_id=score_id,
        state=state,
        is_current=is_current,
        pp=Decimal("123.456789") if state is PerformanceCalculationState.COMPLETED else None,
        star_rating=Decimal("5.43210") if state is PerformanceCalculationState.COMPLETED else None,
        calculator_name="rosu-pp-py",
        calculator_version=calculator_version,
        formula_profile=formula_profile,
        beatmap_file_attachment_id=(
            beatmap_file_attachment_id if state is PerformanceCalculationState.COMPLETED else None
        ),
        beatmap_file_checksum_md5=(
            beatmap_file_checksum_md5 if state is PerformanceCalculationState.COMPLETED else None
        ),
        unavailable_reason=unavailable_reason,
        calculated_at=_NOW if state.is_terminal else None,
    )


def _attachment(
    *,
    beatmap_id: int,
    blob_id: int,
    checksum_md5: str,
) -> BeatmapFileAttachment:
    return BeatmapFileAttachment(
        beatmap_id=beatmap_id,
        blob_id=blob_id,
        checksum_md5=checksum_md5,
        source="official",
        original_filename=f"{beatmap_id}.osu",
        fetched_at=_NOW,
        verified_at=_NOW,
    )
