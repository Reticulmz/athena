"""Performance best projection の refresh / rebuild workflows。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from osu_server.domain.scores.performance import (
    PerformanceCalculation,
    PerformanceCalculationState,
    PerformanceEligibilityPolicy,
)
from osu_server.domain.scores.user_stats import UserStatsPolicy
from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
    BeatmapPerformanceBest,
    BeatmapPerformanceBestBeatmapProjectionSlice,
    BeatmapPerformanceBestProjectionSlice,
    BeatmapPerformanceBestScope,
    BeatmapPerformanceBestUserProjectionSlice,
    UpsertBeatmapPerformanceBest,
)
from osu_server.services.commands.scores.user_stats_projection import (
    replace_current_user_stats_projection,
)

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Score
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork, UnitOfWorkFactory


class RefreshPerformanceBestOutcome(Enum):
    """1 score refresh workflow の永続化結果。"""

    REFRESHED = "refreshed"
    SCORE_NOT_FOUND = "score_not_found"
    SKIPPED_INELIGIBLE_SCORE = "skipped_ineligible_score"
    MISSING_CURRENT_PERFORMANCE = "missing_current_performance"
    MISSING_CURRENT_PP = "missing_current_pp"
    PERFORMANCE_UNAVAILABLE = "performance_unavailable"


class RebuildPerformanceBestProjectionOutcome(Enum):
    """Performance best projection rebuild workflow の永続化結果。"""

    REBUILT = "rebuilt"


@dataclass(frozen=True, slots=True)
class RefreshPerformanceBestCommand:
    """1 つの affected score から projection row を更新する command。

    Args:
        score_id: refresh 対象の accepted score id。

    Raises:
        ValueError: `score_id` が非正の場合。

    制約:
        Performance Calculation row は変更せず、current completed PP を読み取り入力にする。
    """

    score_id: int

    def __post_init__(self) -> None:
        """score_id の永続化 key として不正な非正値を拒否する。"""
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RefreshPerformanceBestResult:
    """1 score refresh workflow の結果。"""

    outcome: RefreshPerformanceBestOutcome
    score_id: int
    projection: BeatmapPerformanceBest | None = None
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RebuildPerformanceBestProjectionCommand:
    """user または beatmap slice の projection rows を再構築する command。

    Args:
        user_id: user slice rebuild 対象の user id。`beatmap_ids` とは同時指定しない。
        beatmap_ids: beatmap slice rebuild 対象の beatmap ids。`user_id` とは同時指定しない。

    Raises:
        ValueError: user scope と beatmap scope が同時指定または未指定の場合。
        ValueError: 指定された id が非正の場合。

    制約:
        Rebuild は Score と current Performance Calculation から projection を再導出する。
    """

    user_id: int | None = None
    beatmap_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """rebuild scope として不正な指定を拒否する。"""
        has_user_scope = self.user_id is not None
        has_beatmap_scope = len(self.beatmap_ids) > 0
        if has_user_scope == has_beatmap_scope:
            msg = "exactly one rebuild scope must be specified"
            raise ValueError(msg)
        if self.user_id is not None and self.user_id <= 0:
            msg = "user_id must be positive"
            raise ValueError(msg)
        if any(beatmap_id <= 0 for beatmap_id in self.beatmap_ids):
            msg = "beatmap_ids must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RebuildPerformanceBestProjectionResult:
    """projection slice rebuild workflow の結果。"""

    outcome: RebuildPerformanceBestProjectionOutcome
    candidate_count: int
    projected_count: int
    skip_reasons: dict[str, int]


@dataclass(frozen=True, slots=True)
class _ProjectionCandidate:
    row: UpsertBeatmapPerformanceBest | None
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PerformanceBestRefresh:
    """Affected score scope refresh の結果。

    属性:
        projection: 更新後の scope winner。winner がない場合は None。
        changed: projection row が変わり得る永続化操作を実行したかどうか。
    """

    projection: BeatmapPerformanceBest | None
    changed: bool


class RefreshPerformanceBestUseCase:
    """1 score の current PP から performance best projection を更新する。"""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        eligibility_policy: PerformanceEligibilityPolicy | None = None,
        user_stats_policy: UserStatsPolicy | None = None,
    ) -> None:
        """UoW factory と eligibility policy を受け取る。"""
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._eligibility_policy: PerformanceEligibilityPolicy = (
            eligibility_policy or PerformanceEligibilityPolicy()
        )
        self._user_stats_policy: UserStatsPolicy = user_stats_policy or UserStatsPolicy()

    async def execute(
        self,
        command: RefreshPerformanceBestCommand,
    ) -> RefreshPerformanceBestResult:
        """affected score の projection row を current completed PP から refresh する。"""
        async with self._unit_of_work_factory() as uow:
            score = await uow.scores.get_by_id(command.score_id)
            if score is None:
                return RefreshPerformanceBestResult(
                    outcome=RefreshPerformanceBestOutcome.SCORE_NOT_FOUND,
                    score_id=command.score_id,
                    skip_reason="score_not_found",
                )

            skip_reason = _score_eligibility_skip_reason(
                score=score,
                eligibility_policy=self._eligibility_policy,
            )
            if skip_reason is not None:
                refresh = await refresh_performance_best_for_current_score(
                    uow,
                    score=score,
                    calculation=None,
                    eligibility_policy=self._eligibility_policy,
                )
                if refresh.changed:
                    _ = await replace_current_user_stats_projection(
                        uow,
                        user_id=score.user_id,
                        ruleset=score.ruleset,
                        playstyle=score.playstyle,
                        policy=self._user_stats_policy,
                    )
                    await uow.commit()
                return RefreshPerformanceBestResult(
                    outcome=RefreshPerformanceBestOutcome.SKIPPED_INELIGIBLE_SCORE,
                    score_id=command.score_id,
                    skip_reason=skip_reason,
                )

            calculation = await uow.score_performance.get_current_for_score(command.score_id)
            candidate = _projection_candidate_for_eligible_score(
                score=score,
                calculation=calculation,
            )
            refresh = await refresh_performance_best_for_current_score(
                uow,
                score=score,
                calculation=calculation,
                eligibility_policy=self._eligibility_policy,
            )
            if candidate.row is None:
                if refresh.changed:
                    _ = await replace_current_user_stats_projection(
                        uow,
                        user_id=score.user_id,
                        ruleset=score.ruleset,
                        playstyle=score.playstyle,
                        policy=self._user_stats_policy,
                    )
                    await uow.commit()
                return RefreshPerformanceBestResult(
                    outcome=_refresh_outcome_for_skip(candidate.skip_reason),
                    score_id=command.score_id,
                    skip_reason=candidate.skip_reason,
                )

            if refresh.changed:
                _ = await replace_current_user_stats_projection(
                    uow,
                    user_id=score.user_id,
                    ruleset=score.ruleset,
                    playstyle=score.playstyle,
                    policy=self._user_stats_policy,
                )
                await uow.commit()

        return RefreshPerformanceBestResult(
            outcome=RefreshPerformanceBestOutcome.REFRESHED,
            score_id=command.score_id,
            projection=refresh.projection,
        )


class RebuildPerformanceBestProjectionUseCase:
    """user または beatmap slice の performance best projection を再構築する。"""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        eligibility_policy: PerformanceEligibilityPolicy | None = None,
        user_stats_policy: UserStatsPolicy | None = None,
    ) -> None:
        """UoW factory と eligibility policy を受け取る。"""
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._eligibility_policy: PerformanceEligibilityPolicy = (
            eligibility_policy or PerformanceEligibilityPolicy()
        )
        self._user_stats_policy: UserStatsPolicy = user_stats_policy or UserStatsPolicy()

    async def execute(
        self,
        command: RebuildPerformanceBestProjectionCommand,
    ) -> RebuildPerformanceBestProjectionResult:
        """指定 slice の projection rows を source data から置き換える。"""
        async with self._unit_of_work_factory() as uow:
            if command.user_id is not None:
                scores = await uow.scores.list_leaderboard_rebuild_candidates_for_user(
                    command.user_id
                )
                slice_: BeatmapPerformanceBestProjectionSlice = (
                    BeatmapPerformanceBestUserProjectionSlice(command.user_id)
                )
            else:
                scores = await uow.scores.list_leaderboard_rebuild_candidates_for_beatmap_ids(
                    command.beatmap_ids
                )
                slice_ = BeatmapPerformanceBestBeatmapProjectionSlice(command.beatmap_ids)

            rows_by_scope: dict[
                BeatmapPerformanceBestScope,
                UpsertBeatmapPerformanceBest,
            ] = {}
            skip_reasons: Counter[str] = Counter()
            for score in scores:
                skip_reason = _score_eligibility_skip_reason(
                    score=score,
                    eligibility_policy=self._eligibility_policy,
                )
                if skip_reason is not None:
                    skip_reasons[skip_reason] += 1
                    continue

                score_id = _require_score_id(score)
                calculation = await uow.score_performance.get_current_for_score(score_id)
                candidate = _projection_candidate_for_eligible_score(
                    score=score,
                    calculation=calculation,
                )
                if candidate.row is None:
                    skip_reasons[candidate.skip_reason or "skipped"] += 1
                    continue

                selected = rows_by_scope.get(candidate.row.scope)
                if selected is None or _candidate_beats_selected(
                    candidate.row,
                    selected,
                ):
                    rows_by_scope[candidate.row.scope] = candidate.row

            rows = tuple(rows_by_scope.values())
            await uow.beatmap_performance_bests.replace_projection_slice(slice_, rows)
            affected_stats_scopes = {
                (score.user_id, score.ruleset, score.playstyle) for score in scores
            }
            for user_id, ruleset, playstyle in sorted(
                affected_stats_scopes,
                key=lambda scope: (scope[0], scope[1].value, scope[2].value),
            ):
                _ = await replace_current_user_stats_projection(
                    uow,
                    user_id=user_id,
                    ruleset=ruleset,
                    playstyle=playstyle,
                    policy=self._user_stats_policy,
                )
            await uow.commit()

        return RebuildPerformanceBestProjectionResult(
            outcome=RebuildPerformanceBestProjectionOutcome.REBUILT,
            candidate_count=len(scores),
            projected_count=len(rows),
            skip_reasons=dict(skip_reasons),
        )


async def replace_user_performance_best_slice(
    uow: UnitOfWork,
    *,
    user_id: int,
    eligibility_policy: PerformanceEligibilityPolicy,
) -> None:
    """Unit of Work 内で 1 user 分の performance best slice を置き換える。

    引数:
        uow: 呼び出し側が所有する command Unit of Work。
        user_id: 置き換え対象の user id。
        eligibility_policy: performance best 候補の eligibility 判定 policy。

    戻り値:
        None。

    例外:
        score id や calculation id が未採番の場合は ValueError を送出する。

    制約:
        commit は呼び出し側が行う。同一 transaction で計算確定と projection 置換を
        まとめたい workflow から使う。
    """
    scores = await uow.scores.list_leaderboard_rebuild_candidates_for_user(user_id)
    rows_by_scope: dict[BeatmapPerformanceBestScope, UpsertBeatmapPerformanceBest] = {}
    for score in scores:
        skip_reason = _score_eligibility_skip_reason(
            score=score,
            eligibility_policy=eligibility_policy,
        )
        if skip_reason is not None:
            continue

        score_id = _require_score_id(score)
        calculation = await uow.score_performance.get_current_for_score(score_id)
        candidate = _projection_candidate_for_eligible_score(
            score=score,
            calculation=calculation,
        )
        if candidate.row is None:
            continue

        selected = rows_by_scope.get(candidate.row.scope)
        if selected is None or _candidate_beats_selected(
            candidate.row,
            selected,
        ):
            rows_by_scope[candidate.row.scope] = candidate.row

    await uow.beatmap_performance_bests.replace_projection_slice(
        BeatmapPerformanceBestUserProjectionSlice(user_id),
        tuple(rows_by_scope.values()),
    )


async def refresh_performance_best_for_current_score(
    uow: UnitOfWork,
    *,
    score: Score,
    calculation: PerformanceCalculation | None,
    eligibility_policy: PerformanceEligibilityPolicy,
) -> PerformanceBestRefresh:
    """Unit of Work 内で affected score の performance best scope だけを更新する。

    引数:
        uow: 呼び出し側が所有する command Unit of Work。
        score: current Performance Calculation が変わった score。
        calculation: score の current Performance Calculation。未取得や ineligible 時は None。
        eligibility_policy: performance best 候補の eligibility 判定 policy。

    戻り値:
        更新後の scope winner と、projection row が変わり得る操作を実行したかどうか。

    制約:
        commit は呼び出し側が行う。PP 低下や unavailable 化で current winner が
        失効したときだけ同一 user/beatmap/mode scope を再選定する。
    """
    scope = _performance_best_scope_for_score(score)
    await uow.beatmap_performance_bests.lock_scope(scope)
    score_id = _require_score_id(score)
    skip_reason = _score_eligibility_skip_reason(
        score=score,
        eligibility_policy=eligibility_policy,
    )
    if skip_reason is not None:
        return await _replace_scope_if_current_score(
            uow,
            scope=scope,
            score_id=score_id,
            eligibility_policy=eligibility_policy,
        )

    candidate = _projection_candidate_for_eligible_score(
        score=score,
        calculation=calculation,
    )
    if candidate.row is None:
        return await _replace_scope_if_current_score(
            uow,
            scope=scope,
            score_id=score_id,
            eligibility_policy=eligibility_policy,
        )

    current = await uow.beatmap_performance_bests.get_best(scope)
    if (
        current is not None
        and current.score_id == candidate.row.score_id
        and current.performance_calculation_id != candidate.row.performance_calculation_id
    ):
        projection = await _replace_performance_best_scope_without_lock(
            uow,
            scope=scope,
            eligibility_policy=eligibility_policy,
        )
        return PerformanceBestRefresh(projection=projection, changed=True)
    if current is not None and not _candidate_beats_projection(candidate.row, current):
        return PerformanceBestRefresh(projection=current, changed=False)

    projection = await uow.beatmap_performance_bests.upsert_if_better(candidate.row)
    return PerformanceBestRefresh(projection=projection, changed=True)


async def _replace_scope_if_current_score(
    uow: UnitOfWork,
    *,
    scope: BeatmapPerformanceBestScope,
    score_id: int,
    eligibility_policy: PerformanceEligibilityPolicy,
) -> PerformanceBestRefresh:
    current = await uow.beatmap_performance_bests.get_best(scope)
    if current is None or current.score_id != score_id:
        return PerformanceBestRefresh(projection=current, changed=False)
    projection = await _replace_performance_best_scope_without_lock(
        uow,
        scope=scope,
        eligibility_policy=eligibility_policy,
    )
    return PerformanceBestRefresh(projection=projection, changed=True)


async def _replace_performance_best_scope_without_lock(
    uow: UnitOfWork,
    *,
    scope: BeatmapPerformanceBestScope,
    eligibility_policy: PerformanceEligibilityPolicy,
) -> BeatmapPerformanceBest | None:
    scores = await uow.scores.list_leaderboard_rebuild_candidates_for_beatmap_ids(
        (scope.beatmap_id,)
    )
    selected: UpsertBeatmapPerformanceBest | None = None
    for score in scores:
        if not _score_matches_performance_scope(score, scope):
            continue
        skip_reason = _score_eligibility_skip_reason(
            score=score,
            eligibility_policy=eligibility_policy,
        )
        if skip_reason is not None:
            continue

        score_id = _require_score_id(score)
        calculation = await uow.score_performance.get_current_for_score(score_id)
        candidate = _projection_candidate_for_eligible_score(
            score=score,
            calculation=calculation,
        )
        if candidate.row is None:
            continue
        if selected is None or _candidate_beats_selected(candidate.row, selected):
            selected = candidate.row

    return await uow.beatmap_performance_bests.replace_scope(scope, selected)


def _score_eligibility_skip_reason(
    *,
    score: Score,
    eligibility_policy: PerformanceEligibilityPolicy,
) -> str | None:
    if not score.leaderboard_eligible_at_submission:
        return "leaderboard_ineligible"
    eligibility = eligibility_policy.evaluate(score)
    if not eligibility.is_eligible:
        return eligibility.reason
    return None


def _performance_best_scope_for_score(score: Score) -> BeatmapPerformanceBestScope:
    return BeatmapPerformanceBestScope(
        user_id=score.user_id,
        beatmap_id=score.beatmap_id,
        ruleset=score.ruleset,
        playstyle=score.playstyle,
    )


def _score_matches_performance_scope(
    score: Score,
    scope: BeatmapPerformanceBestScope,
) -> bool:
    return (
        score.user_id == scope.user_id
        and score.beatmap_id == scope.beatmap_id
        and score.ruleset is scope.ruleset
        and score.playstyle is scope.playstyle
    )


def _projection_candidate_for_eligible_score(
    *,
    score: Score,
    calculation: PerformanceCalculation | None,
) -> _ProjectionCandidate:
    if calculation is None:
        return _ProjectionCandidate(row=None, skip_reason="missing_current_performance")
    if calculation.state is PerformanceCalculationState.UNAVAILABLE:
        return _ProjectionCandidate(row=None, skip_reason="performance_unavailable")
    if calculation.pp is None:
        return _ProjectionCandidate(row=None, skip_reason="missing_current_pp")
    if calculation.state is not PerformanceCalculationState.COMPLETED:
        return _ProjectionCandidate(row=None, skip_reason="performance_unavailable")

    calculation_id = calculation.id
    if calculation_id is None:
        msg = "current performance calculation id must be assigned"
        raise ValueError(msg)
    score_id = _require_score_id(score)
    return _ProjectionCandidate(
        row=UpsertBeatmapPerformanceBest(
            scope=BeatmapPerformanceBestScope(
                user_id=score.user_id,
                beatmap_id=score.beatmap_id,
                ruleset=score.ruleset,
                playstyle=score.playstyle,
            ),
            score_id=score_id,
            performance_calculation_id=calculation_id,
            pp=calculation.pp,
            accuracy=score.accuracy,
            score=score.score,
            submitted_at=score.submitted_at,
        )
    )


def _refresh_outcome_for_skip(skip_reason: str | None) -> RefreshPerformanceBestOutcome:
    if skip_reason == "score_not_found":
        return RefreshPerformanceBestOutcome.SCORE_NOT_FOUND
    if skip_reason == "missing_current_performance":
        return RefreshPerformanceBestOutcome.MISSING_CURRENT_PERFORMANCE
    if skip_reason == "missing_current_pp":
        return RefreshPerformanceBestOutcome.MISSING_CURRENT_PP
    if skip_reason == "performance_unavailable":
        return RefreshPerformanceBestOutcome.PERFORMANCE_UNAVAILABLE
    return RefreshPerformanceBestOutcome.SKIPPED_INELIGIBLE_SCORE


def _candidate_beats_selected(
    candidate: UpsertBeatmapPerformanceBest,
    selected: UpsertBeatmapPerformanceBest,
) -> bool:
    if candidate.pp != selected.pp:
        return candidate.pp > selected.pp
    if candidate.submitted_at != selected.submitted_at:
        return candidate.submitted_at < selected.submitted_at
    return candidate.score_id < selected.score_id


def _candidate_beats_projection(
    candidate: UpsertBeatmapPerformanceBest,
    projection: BeatmapPerformanceBest,
) -> bool:
    if candidate.pp != projection.pp:
        return candidate.pp > projection.pp
    if candidate.submitted_at != projection.submitted_at:
        return candidate.submitted_at < projection.submitted_at
    return candidate.score_id < projection.score_id


def _require_score_id(score: Score) -> int:
    if score.id is None:
        msg = "score id must be assigned before projection refresh"
        raise ValueError(msg)
    return score.id


__all__ = (
    "PerformanceBestRefresh",
    "RebuildPerformanceBestProjectionCommand",
    "RebuildPerformanceBestProjectionOutcome",
    "RebuildPerformanceBestProjectionResult",
    "RebuildPerformanceBestProjectionUseCase",
    "RefreshPerformanceBestCommand",
    "RefreshPerformanceBestOutcome",
    "RefreshPerformanceBestResult",
    "RefreshPerformanceBestUseCase",
    "refresh_performance_best_for_current_score",
    "replace_user_performance_best_slice",
)
