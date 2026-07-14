"""Beatmap leaderboard query use-case.

This read-only use-case resolves a beatmap leaderboard listing without stable
transport request or row types crossing the leaderboard boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.beatmaps import BeatmapFetchState, BeatmapFetchTarget, BeatmapRankStatus
from osu_server.domain.identity.leaderboard_visibility import is_leaderboard_visible_user
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import LeaderboardReadScope

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import Beatmap, BeatmapSet
    from osu_server.domain.identity.authorization import Privileges
    from osu_server.domain.scores.mods import ModCombination
    from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
        BeatmapLeaderboardQueryRepository,
        BeatmapLeaderboardRow,
    )
    from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
        BeatmapScoreListingQueryRepository,
    )
    from osu_server.repositories.interfaces.queries.users import UserQueryRepository
    from osu_server.services.queries.identity import GetFriendEligibleUserIdsQueryUseCase


class _PermissionReader(Protocol):
    async def compute_permissions(self, user_id: int) -> Privileges: ...


_DISPLAYABLE_STATUSES = {
    BeatmapRankStatus.PENDING,
    BeatmapRankStatus.WIP,
    BeatmapRankStatus.GRAVEYARD,
    BeatmapRankStatus.RANKED,
    BeatmapRankStatus.APPROVED,
    BeatmapRankStatus.QUALIFIED,
    BeatmapRankStatus.LOVED,
}
_LEADERBOARD_VISIBLE_STATUSES = {
    BeatmapRankStatus.RANKED,
    BeatmapRankStatus.APPROVED,
    BeatmapRankStatus.QUALIFIED,
    BeatmapRankStatus.LOVED,
}
_LEADERBOARD_ROW_LIMIT = 50


class BeatmapLeaderboardOutcomeKind(Enum):
    HEADER = "header"
    UNAVAILABLE = "unavailable"
    UPDATE_AVAILABLE = "update_available"


class BeatmapLeaderboardResolveReason(Enum):
    KNOWN_CHECKSUM = "known_checksum"
    KNOWN_FILENAME_IN_SET = "known_filename_in_set"
    NOT_SUBMITTED = "not_submitted"
    NOT_FOUND = "not_found"
    PENDING_FETCH = "pending_fetch"
    FAILED_METADATA = "failed_metadata"
    UPDATE_AVAILABLE = "update_available"


@dataclass(slots=True, frozen=True)
class BeatmapLeaderboardRequest:
    beatmap_checksum: str | None
    filename: str | None
    beatmapset_id_hint: int | None
    viewer_user_id: int | None
    ruleset: Ruleset | None
    playstyle: Playstyle
    category: LeaderboardCategory | None
    selected_mods: ModCombination | None
    header_only: bool


@dataclass(slots=True, frozen=True)
class BeatmapLeaderboardHeader:
    beatmap: Beatmap
    beatmapset: BeatmapSet


@dataclass(slots=True, frozen=True)
class BeatmapLeaderboardResult:
    kind: BeatmapLeaderboardOutcomeKind
    header: BeatmapLeaderboardHeader | None
    personal_best: BeatmapLeaderboardRow | None
    rows: tuple[BeatmapLeaderboardRow, ...]
    reason: BeatmapLeaderboardResolveReason


@dataclass(slots=True, frozen=True)
class BeatmapPersonalBestRankQueryInput:
    """Beatmap personal best rank を読むための入力.

    Attributes:
        user_id (int): 対象 User ID.
        beatmap_id (int): 対象 Beatmap ID.
        beatmap_checksum (str): 現在の Beatmap checksum.
        ruleset (Ruleset): 対象 ruleset.
        playstyle (Playstyle): 対象 playstyle.
        category (LeaderboardCategory): 順位を評価する category.
        selected_mods (ModCombination | None): Selected Mods の raw Mod bitflag.
    """

    user_id: int
    beatmap_id: int
    beatmap_checksum: str
    ruleset: Ruleset
    playstyle: Playstyle
    category: LeaderboardCategory = LeaderboardCategory.GLOBAL
    selected_mods: ModCombination | None = None


@dataclass(slots=True, frozen=True)
class BeatmapPersonalBestRankQueryResult:
    """Beatmap personal best rank の読み取り結果。"""

    rank: int | None


@dataclass(slots=True, frozen=True)
class _ViewerLeaderboardContext:
    country: str
    leaderboard_visible: bool


class BeatmapPersonalBestRankQuery:
    """source scores から user の現在の Beatmap 順位を読む query."""

    _leaderboards: BeatmapLeaderboardQueryRepository

    def __init__(self, leaderboards: BeatmapLeaderboardQueryRepository) -> None:
        """読み取り専用 repository を保持する。"""
        self._leaderboards = leaderboards

    async def execute(
        self,
        input_data: BeatmapPersonalBestRankQueryInput,
    ) -> BeatmapPersonalBestRankQueryResult:
        """入力 scope に一致する personal best の順位を返す.

        Args:
            input_data (BeatmapPersonalBestRankQueryInput): 対象 user と leaderboard scope.

        Returns:
            BeatmapPersonalBestRankQueryResult: score がない場合は rank=None の結果.

        Raises:
            ValueError: category と selected_mods の組み合わせが不正な場合.
        """
        if input_data.user_id <= 0:
            return BeatmapPersonalBestRankQueryResult(rank=None)

        row = await self._leaderboards.get_personal_best(
            LeaderboardReadScope(
                beatmap_id=input_data.beatmap_id,
                beatmap_checksum=input_data.beatmap_checksum,
                ruleset=input_data.ruleset,
                playstyle=input_data.playstyle,
                category=input_data.category,
                selected_mods=input_data.selected_mods,
            ),
            viewer_user_id=input_data.user_id,
        )
        return BeatmapPersonalBestRankQueryResult(rank=row.rank if row is not None else None)


class BeatmapLeaderboardQuery:
    """Resolve a transport-neutral beatmap leaderboard listing."""

    _repository: BeatmapScoreListingQueryRepository
    _leaderboards: BeatmapLeaderboardQueryRepository
    _user_repository: UserQueryRepository | None
    _permission_service: _PermissionReader | None
    _friend_eligible_user_ids_query: GetFriendEligibleUserIdsQueryUseCase | None

    def __init__(
        self,
        repository: BeatmapScoreListingQueryRepository,
        leaderboards: BeatmapLeaderboardQueryRepository,
        *,
        user_repository: UserQueryRepository | None = None,
        permission_service: _PermissionReader | None = None,
        friend_eligible_user_ids_query: GetFriendEligibleUserIdsQueryUseCase | None = None,
    ) -> None:
        self._repository = repository
        self._leaderboards = leaderboards
        self._user_repository = user_repository
        self._permission_service = permission_service
        self._friend_eligible_user_ids_query = friend_eligible_user_ids_query

    async def execute(self, request: BeatmapLeaderboardRequest) -> BeatmapLeaderboardResult:
        """Resolve a leaderboard request without command-side mutation."""
        if request.beatmap_checksum is not None:
            beatmap = await self._repository.find_by_checksum(request.beatmap_checksum)
            if beatmap is not None:
                return await self._evaluate_beatmap(
                    beatmap,
                    reason=BeatmapLeaderboardResolveReason.KNOWN_CHECKSUM,
                    request=request,
                )

            if request.filename is not None and request.beatmapset_id_hint is not None:
                update_result = await self._resolve_update_available(
                    checksum_md5=request.beatmap_checksum,
                    beatmapset_id=request.beatmapset_id_hint,
                    filename=request.filename,
                    request=request,
                )
                if update_result.reason is not BeatmapLeaderboardResolveReason.NOT_FOUND:
                    return update_result

            return await self._resolve_checksum_miss(request.beatmap_checksum)

        if request.filename is not None and request.beatmapset_id_hint is not None:
            return await self._resolve_by_filename_in_beatmapset(
                beatmapset_id=request.beatmapset_id_hint,
                filename=request.filename,
                request=request,
            )

        return _unavailable(BeatmapLeaderboardResolveReason.NOT_FOUND)

    async def _resolve_checksum_miss(self, checksum_md5: str) -> BeatmapLeaderboardResult:
        fetch_record = await self._repository.get_fetch_state(
            BeatmapFetchTarget.metadata_by_checksum(checksum_md5)
        )
        if fetch_record is None:
            return _unavailable(BeatmapLeaderboardResolveReason.NOT_FOUND)
        if fetch_record.status is BeatmapFetchState.PENDING_FETCH:
            return _unavailable(BeatmapLeaderboardResolveReason.PENDING_FETCH)
        if fetch_record.status is BeatmapFetchState.FAILED:
            return _unavailable(BeatmapLeaderboardResolveReason.FAILED_METADATA)
        return _unavailable(BeatmapLeaderboardResolveReason.NOT_FOUND)

    async def _resolve_by_filename_in_beatmapset(
        self,
        *,
        beatmapset_id: int,
        filename: str,
        request: BeatmapLeaderboardRequest,
    ) -> BeatmapLeaderboardResult:
        beatmap = await self._repository.find_by_filename_in_beatmapset(
            beatmapset_id,
            filename,
        )

        if beatmap is None:
            return _unavailable(BeatmapLeaderboardResolveReason.NOT_FOUND)

        return await self._evaluate_beatmap(
            beatmap,
            reason=BeatmapLeaderboardResolveReason.KNOWN_FILENAME_IN_SET,
            request=request,
        )

    async def _evaluate_beatmap(
        self,
        beatmap: Beatmap,
        *,
        reason: BeatmapLeaderboardResolveReason,
        request: BeatmapLeaderboardRequest,
    ) -> BeatmapLeaderboardResult:
        beatmapset = await self._repository.get_beatmapset(beatmap.beatmapset_id)

        if beatmapset is None:
            return _unavailable(BeatmapLeaderboardResolveReason.NOT_FOUND)

        if not _is_displayable_in_score_listing(beatmap):
            return _unavailable(BeatmapLeaderboardResolveReason.NOT_SUBMITTED)

        rows: tuple[BeatmapLeaderboardRow, ...] = ()
        personal_best: BeatmapLeaderboardRow | None = None
        if _is_leaderboard_visible_beatmap(beatmap):
            rows, personal_best = await self._resolve_leaderboard_listing(
                request=request,
                beatmap=beatmap,
            )

        return BeatmapLeaderboardResult(
            kind=BeatmapLeaderboardOutcomeKind.HEADER,
            header=BeatmapLeaderboardHeader(
                beatmap=beatmap,
                beatmapset=beatmapset,
            ),
            personal_best=personal_best,
            rows=rows,
            reason=reason,
        )

    async def _resolve_update_available(
        self,
        *,
        checksum_md5: str,
        beatmapset_id: int,
        filename: str,
        request: BeatmapLeaderboardRequest,
    ) -> BeatmapLeaderboardResult:
        beatmap = await self._repository.find_by_filename_in_beatmapset(
            beatmapset_id,
            filename,
        )
        if beatmap is None:
            return _unavailable(BeatmapLeaderboardResolveReason.NOT_FOUND)

        if beatmap.checksum_md5 == checksum_md5:
            return await self._evaluate_beatmap(
                beatmap,
                reason=BeatmapLeaderboardResolveReason.KNOWN_FILENAME_IN_SET,
                request=request,
            )

        beatmapset = await self._repository.get_beatmapset(beatmap.beatmapset_id)
        if beatmapset is None:
            return _unavailable(BeatmapLeaderboardResolveReason.NOT_FOUND)

        if not _is_displayable_in_score_listing(beatmap):
            return _unavailable(BeatmapLeaderboardResolveReason.NOT_SUBMITTED)

        return BeatmapLeaderboardResult(
            kind=BeatmapLeaderboardOutcomeKind.UPDATE_AVAILABLE,
            header=BeatmapLeaderboardHeader(
                beatmap=beatmap,
                beatmapset=beatmapset,
            ),
            personal_best=None,
            rows=(),
            reason=BeatmapLeaderboardResolveReason.UPDATE_AVAILABLE,
        )

    async def _resolve_leaderboard_listing(
        self,
        *,
        request: BeatmapLeaderboardRequest,
        beatmap: Beatmap,
    ) -> tuple[tuple[BeatmapLeaderboardRow, ...], BeatmapLeaderboardRow | None]:
        base_scope = _leaderboard_scope_from_request(
            request=request,
            beatmap=beatmap,
        )
        if base_scope is None:
            return (), None

        viewer_context = await self._resolve_viewer_context(request.viewer_user_id)
        scope = await self._resolve_viewer_dependent_scope(
            scope=base_scope,
            user_id=request.viewer_user_id,
            viewer_context=viewer_context,
        )
        if scope is None:
            return (), None

        rows = await self._leaderboards.list_top_rows(
            scope,
            limit=_LEADERBOARD_ROW_LIMIT,
        )
        personal_best = None
        if (
            request.viewer_user_id is not None
            and viewer_context is not None
            and viewer_context.leaderboard_visible
        ):
            personal_best = await self._leaderboards.get_personal_best(
                scope,
                viewer_user_id=request.viewer_user_id,
            )

        return rows, personal_best

    async def _resolve_viewer_context(
        self,
        user_id: int | None,
    ) -> _ViewerLeaderboardContext | None:
        if user_id is None or self._user_repository is None:
            return None

        user = await self._user_repository.get_by_id(user_id)
        if user is None:
            return None

        leaderboard_visible = False
        if self._permission_service is not None:
            privileges = await self._permission_service.compute_permissions(user_id)
            leaderboard_visible = is_leaderboard_visible_user(privileges)

        return _ViewerLeaderboardContext(
            country=user.country,
            leaderboard_visible=leaderboard_visible,
        )

    async def _resolve_viewer_dependent_scope(
        self,
        *,
        scope: LeaderboardReadScope,
        user_id: int | None,
        viewer_context: _ViewerLeaderboardContext | None,
    ) -> LeaderboardReadScope | None:
        if scope.category is LeaderboardCategory.COUNTRY:
            if viewer_context is None:
                return None
            country = _country_scope_filter(viewer_context.country)
            if country is None:
                return None
            return replace(scope, country=country)

        if scope.category is LeaderboardCategory.FRIENDS:
            if (
                user_id is None
                or viewer_context is None
                or self._friend_eligible_user_ids_query is None
            ):
                return None
            eligible_user_ids = await self._friend_eligible_user_ids_query.execute(
                viewer_user_id=user_id,
            )
            return replace(scope, eligible_user_ids=eligible_user_ids)

        return scope


def _unavailable(reason: BeatmapLeaderboardResolveReason) -> BeatmapLeaderboardResult:
    return BeatmapLeaderboardResult(
        kind=BeatmapLeaderboardOutcomeKind.UNAVAILABLE,
        header=None,
        personal_best=None,
        rows=(),
        reason=reason,
    )


def _is_displayable_in_score_listing(beatmap: Beatmap) -> bool:
    return beatmap.effective_status in _DISPLAYABLE_STATUSES


def _is_leaderboard_visible_beatmap(beatmap: Beatmap) -> bool:
    return beatmap.effective_status in _LEADERBOARD_VISIBLE_STATUSES


def _leaderboard_scope_from_request(
    *,
    request: BeatmapLeaderboardRequest,
    beatmap: Beatmap,
) -> LeaderboardReadScope | None:
    category = request.category
    if (
        request.header_only
        or request.ruleset is None
        or request.playstyle is not Playstyle.VANILLA
        or category is None
    ):
        return None

    selected_mods = (
        request.selected_mods if category is LeaderboardCategory.SELECTED_MODS else None
    )
    if category is LeaderboardCategory.SELECTED_MODS and selected_mods is None:
        return None

    return LeaderboardReadScope(
        beatmap_id=beatmap.id,
        beatmap_checksum=beatmap.checksum_md5,
        ruleset=request.ruleset,
        playstyle=request.playstyle,
        category=category,
        selected_mods=selected_mods,
    )


def _country_scope_filter(country: str) -> str | None:
    normalized = country.strip().upper()
    if normalized in {"", "XX"}:
        return None
    return normalized


__all__ = [
    "BeatmapLeaderboardHeader",
    "BeatmapLeaderboardOutcomeKind",
    "BeatmapLeaderboardQuery",
    "BeatmapLeaderboardRequest",
    "BeatmapLeaderboardResolveReason",
    "BeatmapLeaderboardResult",
    "BeatmapPersonalBestRankQuery",
    "BeatmapPersonalBestRankQueryInput",
    "BeatmapPersonalBestRankQueryResult",
]
