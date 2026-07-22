"""performance best projection の refresh / rebuild workflow を定義する."""

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
    """1 score refresh workflow の永続化結果を表す.

    Attributes:
        REFRESHED (RefreshPerformanceBestOutcome):
            current PP から projection を更新した結果.
        SCORE_NOT_FOUND (RefreshPerformanceBestOutcome):
            対象 score が存在しない結果.
        SKIPPED_INELIGIBLE_SCORE (RefreshPerformanceBestOutcome):
            leaderboard または policy 対象外の結果.
        MISSING_CURRENT_PERFORMANCE (RefreshPerformanceBestOutcome):
            current calculation がない結果.
        MISSING_CURRENT_PP (RefreshPerformanceBestOutcome):
            completed calculation に PP がない結果.
        PERFORMANCE_UNAVAILABLE (RefreshPerformanceBestOutcome):
            current performance が unavailable または pending の結果.
    """

    REFRESHED = "refreshed"
    SCORE_NOT_FOUND = "score_not_found"
    SKIPPED_INELIGIBLE_SCORE = "skipped_ineligible_score"
    MISSING_CURRENT_PERFORMANCE = "missing_current_performance"
    MISSING_CURRENT_PP = "missing_current_pp"
    PERFORMANCE_UNAVAILABLE = "performance_unavailable"


class RebuildPerformanceBestProjectionOutcome(Enum):
    """performance best projection rebuild workflow の永続化結果を表す.

    Attributes:
        REBUILT (RebuildPerformanceBestProjectionOutcome):
            指定 projection slice を source data から置換した結果.
    """

    REBUILT = "rebuilt"


@dataclass(frozen=True, slots=True)
class RefreshPerformanceBestCommand:
    """1件の affected score から projection row を更新する command を表す.

    Attributes:
        score_id (int): refresh 対象となる accepted score の正の永続識別子.

    Notes:
        Performance Calculation row は変更せず、current completed PP を読み取り入力にする.
    """

    score_id: int

    def __post_init__(self) -> None:
        """score_id が正の永続識別子であることを検証する.

        Returns:
            None: score_id を検証し、呼び出し側へ値を返さずに完了する.

        Raises:
            ValueError: score_id が0以下の場合.
        """
        if self.score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RefreshPerformanceBestResult:
    """1 score refresh workflow の結果を表す.

    Attributes:
        outcome (RefreshPerformanceBestOutcome): refresh、skip、または未検出の結果種別.
        score_id (int): command が対象にした score 識別子.
        projection (BeatmapPerformanceBest | None): 更新後または維持した winner. ない場合はNone.
        skip_reason (str | None):
            projection を作れない、または対象外となった理由. 該当しない場合はNone.
    """

    outcome: RefreshPerformanceBestOutcome
    score_id: int
    projection: BeatmapPerformanceBest | None = None
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RebuildPerformanceBestProjectionCommand:
    """user または beatmap slice の projection rows を再構築する command を表す.

    Attributes:
        user_id (int | None):
            rebuild 対象 user の正の識別子. beatmap_ids と排他的で、未指定時はNone.
        beatmap_ids (tuple[int, ...]): rebuild 対象 beatmap の正の識別子列. user_id と排他的.

    Notes:
        Rebuild は Score と current Performance Calculation から projection を再導出する.
    """

    user_id: int | None = None
    beatmap_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """指定 rebuild scope が排他的かつ正の永続識別子だけで構成されることを検証する.

        Returns:
            None: rebuild scope を検証し、呼び出し側へ値を返さずに完了する.

        Raises:
            ValueError:
                user scope と beatmap scope が同時指定または未指定、または id が0以下の場合.
        """
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
    """projection slice rebuild workflow の結果を表す.

    Attributes:
        outcome (RebuildPerformanceBestProjectionOutcome): projection slice の置換結果.
        candidate_count (int): rebuild source として読み込んだ score 件数.
        projected_count (int): slice に保存した winner projection 件数.
        skip_reasons (dict[str, int]): projection 候補から除外した理由ごとの件数.
    """

    outcome: RebuildPerformanceBestProjectionOutcome
    candidate_count: int
    projected_count: int
    skip_reasons: dict[str, int]


@dataclass(frozen=True, slots=True)
class _ProjectionCandidate:
    """eligible score から導出した projection candidate または除外理由を表す.

    Attributes:
        row (UpsertBeatmapPerformanceBest | None):
            projection に保存する candidate row. 除外時はNone.
        skip_reason (str | None): row を作れない理由. candidate を作れた場合はNone.
    """

    row: UpsertBeatmapPerformanceBest | None
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PerformanceBestRefresh:
    """affected score scope refresh の結果を表す.

    Attributes:
        projection (BeatmapPerformanceBest | None):
            更新後または既存の scope winner. winner がない場合はNone.
        changed (bool): projection row を変え得る永続化操作を実行したか.
    """

    projection: BeatmapPerformanceBest | None
    changed: bool


class RefreshPerformanceBestUseCase:
    """1 score の current PP から performance best projection を更新する."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        eligibility_policy: PerformanceEligibilityPolicy | None = None,
        user_stats_policy: UserStatsPolicy | None = None,
    ) -> None:
        """更新用 projection refresh に必要な Unit of Work factory と policy を受け取る.

        Args:
            unit_of_work_factory (UnitOfWorkFactory):
                score、projection、stats を一貫して扱う factory.
            eligibility_policy (PerformanceEligibilityPolicy | None):
                performance candidate の対象可否を判定する policy. 未指定時は既定 policy.
            user_stats_policy (UserStatsPolicy | None):
                changed scope の user stats を再導出する policy. 未指定時は既定 policy.
        """
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._eligibility_policy: PerformanceEligibilityPolicy = (
            eligibility_policy or PerformanceEligibilityPolicy()
        )
        self._user_stats_policy: UserStatsPolicy = user_stats_policy or UserStatsPolicy()

    async def execute(
        self,
        command: RefreshPerformanceBestCommand,
    ) -> RefreshPerformanceBestResult:
        """対象 score の projection row を current completed PP から refresh する.

        Args:
            command (RefreshPerformanceBestCommand): refresh 対象 score を指定する command.

        Returns:
            RefreshPerformanceBestResult: refresh、skip、または score 未検出の結果.

        Notes:
            projection が変わる場合だけ同じ transaction で current user stats を更新する.
        """
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
    """user または beatmap slice の performance best projection を再構築する."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        eligibility_policy: PerformanceEligibilityPolicy | None = None,
        user_stats_policy: UserStatsPolicy | None = None,
    ) -> None:
        """再構築用 projection rebuild に必要な Unit of Work factory と policy を受け取る.

        Args:
            unit_of_work_factory (UnitOfWorkFactory):
                source score、projection、stats を一貫して扱う factory.
            eligibility_policy (PerformanceEligibilityPolicy | None):
                performance candidate の対象可否を判定する policy. 未指定時は既定 policy.
            user_stats_policy (UserStatsPolicy | None):
                affected user stats を再導出する policy. 未指定時は既定 policy.
        """
        self._unit_of_work_factory: UnitOfWorkFactory = unit_of_work_factory
        self._eligibility_policy: PerformanceEligibilityPolicy = (
            eligibility_policy or PerformanceEligibilityPolicy()
        )
        self._user_stats_policy: UserStatsPolicy = user_stats_policy or UserStatsPolicy()

    async def execute(
        self,
        command: RebuildPerformanceBestProjectionCommand,
    ) -> RebuildPerformanceBestProjectionResult:
        """指定 slice の projection rows を source data から置き換える.

        Args:
            command (RebuildPerformanceBestProjectionCommand):
                user または beatmap の rebuild scope を指定する command.

        Returns:
            RebuildPerformanceBestProjectionResult:
                読み込んだ候補、保存 projection、除外理由の集計.

        Notes:
            slice 内で影響を受けた各 user/ruleset/playstyle の current user stats を再導出する.
        """
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
    """Unit of Work 内で1 user 分の performance best slice を置き換える.

    Args:
        uow (UnitOfWork): 呼び出し側が所有する command Unit of Work.
        user_id (int): 置き換え対象 user の永続識別子.
        eligibility_policy (PerformanceEligibilityPolicy):
            performance best candidate の対象可否を判定する policy.

    Returns:
        None: user slice を置き換え、呼び出し側へ値を返さずに完了する.

    Raises:
        ValueError: candidate score または current calculation の id が未採番の場合.

    Notes:
        commit は呼び出し側が行う. 同一 transaction で計算確定と projection 置換を
        まとめる workflow から使う.
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
    """Unit of Work 内で affected score の performance best scope だけを更新する.

    Args:
        uow (UnitOfWork): 呼び出し側が所有する command Unit of Work.
        score (Score): current Performance Calculation が変わった score.
        calculation (PerformanceCalculation | None):
            score の current calculation. 未取得または対象外時はNone.
        eligibility_policy (PerformanceEligibilityPolicy):
            performance best candidate の対象可否を判定する policy.

    Returns:
        PerformanceBestRefresh: 更新後の scope winner と永続化操作の実行有無.

    Raises:
        ValueError: score または candidate calculation の id が未採番の場合.

    Notes:
        commit は呼び出し側が行う. current winner が失効したときだけ
        同一 user/beatmap/mode scope を再選定する.
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
    """対象 score が既存 winner の場合だけ scope を再選定する.

    Args:
        uow (UnitOfWork): lock 済み scope を操作する command Unit of Work.
        scope (BeatmapPerformanceBestScope): 再選定する user/beatmap/ruleset/playstyle scope.
        score_id (int): current candidate と比較する score 識別子.
        eligibility_policy (PerformanceEligibilityPolicy):
            replacement candidate の対象可否を判定する policy.

    Returns:
        PerformanceBestRefresh: 既存 winner または再選定後 winner と変更有無.
    """
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
    """既に lock 済みの performance best scope の winner を source score から再選定する.

    Args:
        uow (UnitOfWork): scope の winner を照会および置換する command Unit of Work.
        scope (BeatmapPerformanceBestScope): 再選定する user/beatmap/ruleset/playstyle scope.
        eligibility_policy (PerformanceEligibilityPolicy): candidate の対象可否を判定する policy.

    Returns:
        BeatmapPerformanceBest | None: 置換後 winner. 有効 candidate がない場合はNone.
    """
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
    """対象 score が performance best candidate から除外される理由を返す.

    Args:
        score (Score): leaderboard と performance policy を評価する score.
        eligibility_policy (PerformanceEligibilityPolicy): performance 対象可否を判定する policy.

    Returns:
        str | None: 除外理由. candidate にできる場合はNone.
    """
    if not score.leaderboard_eligible_at_submission:
        return "leaderboard_ineligible"
    eligibility = eligibility_policy.evaluate(score)
    if not eligibility.is_eligible:
        return eligibility.reason
    return None


def _performance_best_scope_for_score(score: Score) -> BeatmapPerformanceBestScope:
    """対象 score から performance best の一意な projection scope を構成する.

    Args:
        score (Score): user、beatmap、ruleset、playstyle を持つ score.

    Returns:
        BeatmapPerformanceBestScope: score が属する projection scope.
    """
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
    """対象 score が指定 performance best scope に厳密一致するか判定する.

    Args:
        score (Score): scope との一致を調べる score.
        scope (BeatmapPerformanceBestScope): user、beatmap、ruleset、playstyle の比較対象.

    Returns:
        bool: 4つの scope component がすべて一致する場合はTrue.
    """
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
    """対象 eligible score と current calculation から projection candidate を導出する.

    Args:
        score (Score): projection candidate に変換する eligible score.
        calculation (PerformanceCalculation | None):
            score の current performance calculation. 未取得時はNone.

    Returns:
        _ProjectionCandidate: upsert row、または candidate を作れない理由.

    Raises:
        ValueError: completed calculation の id が未採番の場合.
    """
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
    """除外理由を公開 refresh outcome へ変換する.

    Args:
        skip_reason (str | None): candidate 導出または score 解決で得た除外理由.

    Returns:
        RefreshPerformanceBestOutcome: 理由に対応する公開 outcome. 未知理由は対象外 outcome.
    """
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
    """2つの upsert candidate のうち candidate が selected より優先されるか判定する.

    Args:
        candidate (UpsertBeatmapPerformanceBest): 新しく比較する projection candidate.
        selected (UpsertBeatmapPerformanceBest): 現在選ばれている projection candidate.

    Returns:
        bool: PP 降順、submitted_at 昇順、score id 昇順で candidate が優先される場合はTrue.
    """
    if candidate.pp != selected.pp:
        return candidate.pp > selected.pp
    if candidate.submitted_at != selected.submitted_at:
        return candidate.submitted_at < selected.submitted_at
    return candidate.score_id < selected.score_id


def _candidate_beats_projection(
    candidate: UpsertBeatmapPerformanceBest,
    projection: BeatmapPerformanceBest,
) -> bool:
    """新しい upsert candidate が現在の保存 projection より優先されるか判定する.

    Args:
        candidate (UpsertBeatmapPerformanceBest): 保存 projection と比較する candidate.
        projection (BeatmapPerformanceBest): 現在保存されている scope winner.

    Returns:
        bool: PP 降順、submitted_at 昇順、score id 昇順で candidate が優先される場合はTrue.
    """
    if candidate.pp != projection.pp:
        return candidate.pp > projection.pp
    if candidate.submitted_at != projection.submitted_at:
        return candidate.submitted_at < projection.submitted_at
    return candidate.score_id < projection.score_id


def _require_score_id(score: Score) -> int:
    """更新処理に必要な score id が割り当て済みであることを確認する.

    Args:
        score (Score): 永続識別子を持つ必要がある score.

    Returns:
        int: 割り当て済みの score 識別子.

    Raises:
        ValueError: score id がまだ割り当てられていない場合.
    """
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
