"""Committed in-memory state から Beatmap Leaderboard を構築する query adapter を提供する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.leaderboard_visibility import is_leaderboard_visible_user
from osu_server.domain.scores.leaderboards import ScoreRankKey, score_beats_current
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    BeatmapLeaderboardRow,
    ScoreHitCounts,
)

if TYPE_CHECKING:
    from decimal import Decimal

    from osu_server.domain.identity.users import User
    from osu_server.domain.scores.score import Score
    from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
        BeatmapLeaderboardUserBest,
    )
    from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
        LeaderboardReadScope,
    )
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

_VISIBLE_BEATMAP_STATUSES = frozenset(
    {
        BeatmapRankStatus.RANKED,
        BeatmapRankStatus.APPROVED,
        BeatmapRankStatus.LOVED,
        BeatmapRankStatus.QUALIFIED,
    }
)
_PP_VISIBLE_BEATMAP_STATUSES = frozenset(
    {
        BeatmapRankStatus.RANKED,
        BeatmapRankStatus.APPROVED,
    }
)
_MAX_QUERY_LIMIT = 50


@dataclass(slots=True, frozen=True)
class _LeaderboardCandidate:
    """Leaderboard の順位計算に必要な Score, User, rank key をまとめる値.

    Attributes:
        score (Score): 表示と順位計算の対象 Score.
        user (User): score owner の表示用 User.
        rank_key (ScoreRankKey): Score の順位を比較する key.

    Notes:
        frozen dataclass であり, candidate 作成後に field は変更できない.
    """

    score: Score
    user: User
    rank_key: ScoreRankKey


class InMemoryBeatmapLeaderboardQueryRepository:
    """Committed memory state の Mod 別 projection から leaderboard を構築する adapter.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): query ごとの committed snapshot を生成する factory.

    Notes:
        各 query は snapshot だけを読み, Score, projection, User, Replay state を変更しない.
    """

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Committed snapshot を取得する factory を保持する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): read に使用する committed state factory.
        """
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def list_top_rows(
        self,
        scope: LeaderboardReadScope,
        *,
        limit: int,
    ) -> tuple[BeatmapLeaderboardRow, ...]:
        """Scope 内の leaderboard row を上位から指定件数だけ取得する.

        Args:
            scope (LeaderboardReadScope): Beatmap checksum, ruleset, playstyle, category,
                Mod 条件を含む read scope.
            limit (int): 要求する最大 row 件数.

        Returns:
            tuple[BeatmapLeaderboardRow, ...]: rank 1 からの上位 row. 件数は 0 から 50 に
            clamp される.

        Raises:
            ValueError: SELECTED_MODS category で scope.selected_mods が None の場合.

        Notes:
            ranking は有効で可視な User の代表 Score を ScoreRankKey 順に並べて計算する. state を
            変更しない.
        """
        state = self._factory.snapshot()
        candidates = _ranked_candidates(state, scope)
        capped_limit = min(max(limit, 0), _MAX_QUERY_LIMIT)
        return tuple(
            _candidate_to_row(state=state, candidate=candidate, rank=rank)
            for rank, candidate in enumerate(candidates[:capped_limit], start=1)
        )

    async def get_personal_best(
        self,
        scope: LeaderboardReadScope,
        *,
        viewer_user_id: int,
    ) -> BeatmapLeaderboardRow | None:
        """Viewer の代表 Score と scope 内の実順位を返す.

        Args:
            scope (LeaderboardReadScope): Beatmap checksum, ruleset, playstyle, category,
                Mod 条件を含む read scope.
            viewer_user_id (int): Personal Best を取得する User の ID.

        Returns:
            BeatmapLeaderboardRow | None: Viewer の代表 row. 対象がなければ None.

        Raises:
            ValueError: SELECTED_MODS category で scope.selected_mods が None の場合.

        Notes:
            rank は filtered candidate 全体に対する 1 始まりの実順位であり, state を変更しない.
        """
        state = self._factory.snapshot()
        candidates = _ranked_candidates(state, scope)
        for rank, candidate in enumerate(candidates, start=1):
            if candidate.score.user_id == viewer_user_id:
                return _candidate_to_row(state=state, candidate=candidate, rank=rank)
        return None


def _ranked_candidates(
    state: InMemoryCommandRepositoryState,
    scope: LeaderboardReadScope,
) -> tuple[_LeaderboardCandidate, ...]:
    """Scope を満たす User ごとの最良 Score candidate を順位順に構築する.

    Args:
        state (InMemoryCommandRepositoryState): Beatmap, projection, Score, User, Role を含む
            snapshot.
        scope (LeaderboardReadScope): ranking に使用する read scope.

    Returns:
        tuple[_LeaderboardCandidate, ...]: User ごとの最良 candidate を ScoreRankKey 順に並べた
            tuple.
        Beatmap が現在表示可能でなければ空の tuple.

    Raises:
        ValueError: SELECTED_MODS category で scope.selected_mods が None の場合.

    Notes:
        同じ User の candidate は score_beats_current() が True の Score だけで置き換える. state を
        変更しない.
    """
    if not _beatmap_is_currently_visible(state, scope):
        return ()

    best_by_user_id: dict[int, _LeaderboardCandidate] = {}
    for projection in state.beatmap_leaderboard_user_bests_by_id.values():
        candidate = _candidate_from_projection(state, scope, projection)
        if candidate is None:
            continue
        current = best_by_user_id.get(projection.scope.user_id)
        if current is None or score_beats_current(candidate.rank_key, current.rank_key):
            best_by_user_id[projection.scope.user_id] = candidate

    candidates = list(best_by_user_id.values())
    candidates.sort(key=lambda candidate: candidate.rank_key.ordering_key)
    return tuple(candidates)


def _beatmap_is_currently_visible(
    state: InMemoryCommandRepositoryState,
    scope: LeaderboardReadScope,
) -> bool:
    """Read scope の Beatmap が現在 leaderboard に表示可能かを判定する.

    Args:
        state (InMemoryCommandRepositoryState): Beatmap を含む snapshot.
        scope (LeaderboardReadScope): Beatmap ID と checksum を含む read scope.

    Returns:
        bool: Beatmap が存在し checksum が一致し effective status が表示対象なら True.

    Notes:
        state を変更しない.
    """
    beatmap = state.beatmaps_by_id.get(scope.beatmap_id)
    if beatmap is None:
        return False
    return (
        beatmap.checksum_md5 == scope.beatmap_checksum
        and beatmap.effective_status in _VISIBLE_BEATMAP_STATUSES
    )


def _candidate_from_projection(
    state: InMemoryCommandRepositoryState,
    scope: LeaderboardReadScope,
    projection: BeatmapLeaderboardUserBest,
) -> _LeaderboardCandidate | None:
    """Projection が scope を満たす場合に ranking candidate へ変換する.

    Args:
        state (InMemoryCommandRepositoryState): projection の参照先を含む snapshot.
        scope (LeaderboardReadScope): candidate の read scope.
        projection (BeatmapLeaderboardUserBest): User ごとの best Score projection.

    Returns:
        _LeaderboardCandidate | None: 有効, 可視, category 適合の Score と User から作る candidate.
        条件を満たさなければ None.

    Raises:
        ValueError: SELECTED_MODS category で scope.selected_mods が None の場合.

    Notes:
        Score は projection の owner と Mod に一致し, current eligibility を満たす必要がある.
        state を変更しない.
    """
    if not _projection_matches_scope(projection, scope):
        return None

    score = state.scores_by_id.get(projection.score_id)
    if (
        score is None
        or score.id is None
        or not _score_is_currently_eligible(state, scope, score)
        or score.user_id != projection.scope.user_id
        or score.mods != projection.scope.mods
    ):
        return None
    user = state.users_by_id.get(score.user_id)
    if (
        user is None
        or not _user_is_visible(state, user.id)
        or not _passes_category_filter(scope, user.id, user.country)
    ):
        return None
    return _LeaderboardCandidate(
        score=score,
        user=user,
        rank_key=ScoreRankKey(
            score=score.score,
            submitted_at=score.submitted_at,
            score_id=score.id,
        ),
    )


def _projection_matches_scope(
    projection: BeatmapLeaderboardUserBest,
    scope: LeaderboardReadScope,
) -> bool:
    """Projection の scope が leaderboard read scope に一致するかを判定する.

    Args:
        projection (BeatmapLeaderboardUserBest): 比較する User best projection.
        scope (LeaderboardReadScope): Beatmap, ruleset, playstyle, category, selected Mods の条件.

    Returns:
        bool: Beatmap ID/checksum/ruleset/playstyle が一致し, 必要なら selected Mod bitmask も
            一致すれば True. それ以外は False.

    Raises:
        ValueError: scope.category が SELECTED_MODS で scope.selected_mods が None の場合.

    Notes:
        ruleset と playstyle は value equality ではなく identity で比較する.
        selected Mods は implied Mod へ正規化せず raw bitmask の完全一致で比較する.
    """
    projection_scope = projection.scope
    if (
        projection_scope.beatmap_id != scope.beatmap_id
        or projection_scope.beatmap_checksum != scope.beatmap_checksum
        or projection_scope.ruleset is not scope.ruleset
        or projection_scope.playstyle is not scope.playstyle
    ):
        return False
    if scope.category is not LeaderboardCategory.SELECTED_MODS:
        return True
    selected_mods = scope.selected_mods
    if selected_mods is None:
        msg = "selected-mods scope requires selected_mods"
        raise ValueError(msg)
    # SQLAlchemy実装と同じくraw bitmaskを完全一致させ, implied Modへ正規化しない.
    return projection_scope.mods == selected_mods


def _score_is_currently_eligible(
    state: InMemoryCommandRepositoryState,
    scope: LeaderboardReadScope,
    score: Score,
) -> bool:
    """Score が read scope の現在有効な leaderboard entry かを判定する.

    Args:
        state (InMemoryCommandRepositoryState): Score eligibility 索引を含む snapshot.
        scope (LeaderboardReadScope): Beatmap checksum, ruleset, playstyle を含む read scope.
        score (Score): 判定する Score.

    Returns:
        bool: ID を持ち, Beatmap/checksum/ruleset/playstyle が scope に一致し, passed かつ
            eligibility 索引が True なら True. それ以外は False.

    Notes:
        ruleset と playstyle は identity で比較し, state と score を変更しない.
    """
    score_id = score.id
    if score_id is None:
        return False
    return (
        score.beatmap_id == scope.beatmap_id
        and score.beatmap_checksum == scope.beatmap_checksum
        and score.ruleset is scope.ruleset
        and score.playstyle is scope.playstyle
        and score.passed
        and state.score_leaderboard_eligibility_by_id.get(score_id, False)
    )


def _user_is_visible(state: InMemoryCommandRepositoryState, user_id: int) -> bool:
    """User に割り当てられた Role permissions から leaderboard 可視性を判定する.

    Args:
        state (InMemoryCommandRepositoryState): Role と User Role assignment を含む snapshot.
        user_id (int): 可視性を判定する User の ID.

    Returns:
        bool: 合成した Privileges が leaderboard-visible なら True, それ以外は False.

    Notes:
        存在しない Role ID は無視し, state を変更しない.
    """
    privileges = Privileges.NONE
    for role_id in state.role_ids_by_user_id.get(user_id, set()):
        role = state.roles_by_id.get(role_id)
        if role is not None:
            privileges |= role.permissions
    return is_leaderboard_visible_user(privileges)


def _passes_category_filter(
    scope: LeaderboardReadScope,
    user_id: int,
    country: str,
) -> bool:
    """User が scope の country または friends category 条件を満たすかを判定する.

    Args:
        scope (LeaderboardReadScope): category と category 固有の条件を含む read scope.
        user_id (int): category membership を確認する User の ID.
        country (str): User の country code.

    Returns:
        bool: COUNTRY では有効な scope.country と country が一致し, FRIENDS では
            eligible_user_ids に user_id が含まれ, それ以外の category では True.

    Notes:
        COUNTRY の scope.country が None または XX なら False. FRIENDS の eligible_user_ids が None
        なら False.
    """
    if scope.category is LeaderboardCategory.COUNTRY:
        return scope.country is not None and scope.country != "XX" and country == scope.country
    if scope.category is LeaderboardCategory.FRIENDS:
        return scope.eligible_user_ids is not None and user_id in scope.eligible_user_ids
    return True


def _candidate_to_row(
    *,
    state: InMemoryCommandRepositoryState,
    candidate: _LeaderboardCandidate,
    rank: int,
) -> BeatmapLeaderboardRow:
    """Ranking candidate を client-facing leaderboard row に変換する.

    Args:
        state (InMemoryCommandRepositoryState): Replay と current Performance calculation を含む
            snapshot.
        candidate (_LeaderboardCandidate): 変換する Score/User/rank key の組.
        rank (int): row に設定する 1 始まりの順位.

    Returns:
        BeatmapLeaderboardRow: Score presentation fields, Replay 有無, current PP を含む row.

    Raises:
        AssertionError: candidate.score.id が None の場合.

    Notes:
        state と candidate を変更しない.
    """
    score = candidate.score
    assert score.id is not None
    return BeatmapLeaderboardRow(
        score_id=score.id,
        user_id=score.user_id,
        username=candidate.user.username,
        beatmap_id=score.beatmap_id,
        ruleset=score.ruleset,
        playstyle=score.playstyle,
        score=score.score,
        max_combo=score.max_combo,
        hit_counts=ScoreHitCounts(
            n50=score.n50,
            n100=score.n100,
            n300=score.n300,
            miss=score.miss,
            katu=score.katu,
            geki=score.geki,
        ),
        perfect=score.perfect,
        displayed_mods=score.mods,
        rank=rank,
        submitted_at=score.submitted_at,
        has_replay=any(replay.score_id == score.id for replay in state.replays_by_id.values()),
        pp=_current_pp_for_score(state, score),
    )


def _current_pp_for_score(
    state: InMemoryCommandRepositoryState,
    score: Score,
) -> Decimal | None:
    """Score に表示可能な current PerformanceCalculation の PP を取得する.

    Args:
        state (InMemoryCommandRepositoryState): Beatmap と Performance calculation を含む snapshot.
        score (Score): PP を取得する Score.

    Returns:
        Decimal | None: Score の current calculation PP. Score ID, Beatmap, status,
            current calculation 索引, calculation 整合性のいずれかが不適合なら None.

    Notes:
        PP は RANKED または APPROVED Beatmap にだけ表示する. calculation は Score ID が一致し,
        is_current が True である必要がある. state と score を変更しない.
    """
    if score.id is None:
        return None
    beatmap = state.beatmaps_by_id.get(score.beatmap_id)
    if beatmap is None or beatmap.effective_status not in _PP_VISIBLE_BEATMAP_STATUSES:
        return None

    calculation_id = state.current_performance_calculation_id_by_score_id.get(score.id)
    if calculation_id is None:
        return None
    calculation = state.performance_calculations_by_id.get(calculation_id)
    if calculation is None or calculation.score_id != score.id or not calculation.is_current:
        return None
    return calculation.pp


__all__ = ["InMemoryBeatmapLeaderboardQueryRepository"]
