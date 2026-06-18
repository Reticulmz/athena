"""Beatmap score listing query use-case.

Query-side beatmap resolution for score listing compatibility. This use-case
provides read-only beatmap resolution without triggering command-side mutations
or background fetch workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.beatmaps import BeatmapRankStatus
from osu_server.domain.compatibility.stable.getscores import (
    GetscoresOutcomeKind,
    GetscoresPersonalBest,
    GetscoresRequest,
    GetscoresResolvedHeader,
    GetscoresResolveOutcome,
    GetscoresResolveReason,
)
from osu_server.domain.identity.leaderboard_visibility import is_leaderboard_visible_user
from osu_server.domain.scores.leaderboards import (
    LeaderboardModFilter,
    filter_from_mod_combination,
)
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import LeaderboardReadScope

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import Beatmap
    from osu_server.domain.identity.authorization import Privileges
    from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
        BeatmapLeaderboardQueryRepository,
        BeatmapLeaderboardRow,
    )
    from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
        BeatmapScoreListingQueryRepository,
    )
    from osu_server.repositories.interfaces.queries.personal_bests import (
        PersonalBestQueryRepository,
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
_LOCAL_LEADERBOARD_TYPE = 1
_SELECTED_MODS_LEADERBOARD_TYPE = 2
_FRIENDS_LEADERBOARD_TYPE = 3
_COUNTRY_LEADERBOARD_TYPE = 4


@dataclass(slots=True, frozen=True)
class _ViewerLeaderboardContext:
    country: str
    leaderboard_visible: bool


class BeatmapScoreListingQuery:
    """Score listing beatmap resolution query use-case (read-only)."""

    _repository: BeatmapScoreListingQueryRepository
    _personal_bests: PersonalBestQueryRepository
    _leaderboards: BeatmapLeaderboardQueryRepository | None
    _user_repository: UserQueryRepository | None
    _permission_service: _PermissionReader | None
    _friend_eligible_user_ids_query: GetFriendEligibleUserIdsQueryUseCase | None

    def __init__(
        self,
        repository: BeatmapScoreListingQueryRepository,
        personal_bests: PersonalBestQueryRepository,
        leaderboards: BeatmapLeaderboardQueryRepository | None = None,
        *,
        user_repository: UserQueryRepository | None = None,
        permission_service: _PermissionReader | None = None,
        friend_eligible_user_ids_query: GetFriendEligibleUserIdsQueryUseCase | None = None,
    ) -> None:
        self._repository = repository
        self._personal_bests = personal_bests
        self._leaderboards = leaderboards
        self._user_repository = user_repository
        self._permission_service = permission_service
        self._friend_eligible_user_ids_query = friend_eligible_user_ids_query

    async def resolve(
        self,
        request: GetscoresRequest,
        *,
        user_id: int | None = None,
    ) -> GetscoresResolveOutcome:
        """Resolve a parsed getscores request without command-side mutation."""
        if request.checksum_md5 is not None:
            beatmap = await self._repository.find_by_checksum(request.checksum_md5)
            if beatmap is not None:
                return await self._evaluate_beatmap(
                    beatmap,
                    reason=GetscoresResolveReason.KNOWN_CHECKSUM,
                    request=request,
                    user_id=user_id,
                )

            if request.filename is not None and request.beatmapset_id_hint is not None:
                return await self._resolve_update_available(
                    checksum_md5=request.checksum_md5,
                    beatmapset_id=request.beatmapset_id_hint,
                    filename=request.filename,
                    request=request,
                    user_id=user_id,
                )

            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if request.filename is not None and request.beatmapset_id_hint is not None:
            return await self._resolve_by_filename_in_beatmapset(
                beatmapset_id=request.beatmapset_id_hint,
                filename=request.filename,
                request=request,
                user_id=user_id,
            )

        return _unavailable(GetscoresResolveReason.NOT_FOUND)

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
    ) -> GetscoresResolveOutcome:
        """Resolve beatmap by checksum for getscores response."""
        beatmap = await self._repository.find_by_checksum(checksum_md5)

        if beatmap is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        return await self._evaluate_beatmap(
            beatmap,
            reason=GetscoresResolveReason.KNOWN_CHECKSUM,
            request=None,
            user_id=None,
        )

    async def resolve_by_filename_in_beatmapset(
        self,
        beatmapset_id: int,
        filename: str,
    ) -> GetscoresResolveOutcome:
        """Resolve beatmap by filename within a beatmapset."""
        return await self._resolve_by_filename_in_beatmapset(
            beatmapset_id=beatmapset_id,
            filename=filename,
            request=None,
            user_id=None,
        )

    async def _resolve_by_filename_in_beatmapset(
        self,
        *,
        beatmapset_id: int,
        filename: str,
        request: GetscoresRequest | None,
        user_id: int | None,
    ) -> GetscoresResolveOutcome:
        """Resolve beatmap by filename within a beatmapset."""
        beatmap = await self._repository.find_by_filename_in_beatmapset(
            beatmapset_id,
            filename,
        )

        if beatmap is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        return await self._evaluate_beatmap(
            beatmap,
            reason=GetscoresResolveReason.KNOWN_FILENAME_IN_SET,
            request=request,
            user_id=user_id,
        )

    async def _evaluate_beatmap(
        self,
        beatmap: Beatmap,
        *,
        reason: GetscoresResolveReason,
        request: GetscoresRequest | None,
        user_id: int | None,
    ) -> GetscoresResolveOutcome:
        """Evaluate a found beatmap for getscores header."""
        beatmapset = await self._repository.get_beatmapset(beatmap.beatmapset_id)

        if beatmapset is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if not _is_displayable_in_score_listing(beatmap):
            return _unavailable(GetscoresResolveReason.NOT_SUBMITTED)

        personal_best: GetscoresPersonalBest | None = None
        score_rows: tuple[GetscoresPersonalBest, ...] = ()
        if self._leaderboards is None:
            personal_best = await self._resolve_personal_best(
                request=request,
                beatmap=beatmap,
                user_id=user_id,
            )
        elif _is_leaderboard_visible_beatmap(beatmap):
            score_rows, personal_best = await self._resolve_leaderboard_listing(
                request=request,
                beatmap=beatmap,
                user_id=user_id,
            )

        return GetscoresResolveOutcome(
            kind=GetscoresOutcomeKind.HEADER,
            header=GetscoresResolvedHeader(
                beatmap=beatmap,
                beatmapset=beatmapset,
                personal_best=personal_best,
                score_rows=score_rows,
            ),
            reason=reason,
        )

    async def _resolve_update_available(
        self,
        *,
        checksum_md5: str,
        beatmapset_id: int,
        filename: str,
        request: GetscoresRequest,
        user_id: int | None,
    ) -> GetscoresResolveOutcome:
        beatmap = await self._repository.find_by_filename_in_beatmapset(
            beatmapset_id,
            filename,
        )
        if beatmap is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if beatmap.checksum_md5 == checksum_md5:
            return await self._evaluate_beatmap(
                beatmap,
                reason=GetscoresResolveReason.KNOWN_FILENAME_IN_SET,
                request=request,
                user_id=user_id,
            )

        beatmapset = await self._repository.get_beatmapset(beatmap.beatmapset_id)
        if beatmapset is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if not _is_displayable_in_score_listing(beatmap):
            return _unavailable(GetscoresResolveReason.NOT_SUBMITTED)

        return GetscoresResolveOutcome(
            kind=GetscoresOutcomeKind.UPDATE_AVAILABLE,
            header=GetscoresResolvedHeader(
                beatmap=beatmap,
                beatmapset=beatmapset,
            ),
            reason=GetscoresResolveReason.UPDATE_AVAILABLE,
        )

    async def _resolve_personal_best(
        self,
        *,
        request: GetscoresRequest | None,
        beatmap: Beatmap,
        user_id: int | None,
    ) -> GetscoresPersonalBest | None:
        if request is None or user_id is None or request.song_select is True:
            return None

        ruleset = _ruleset_from_request(request)
        if ruleset is None:
            return None

        return await self._personal_bests.get_personal_best(
            user_id=user_id,
            beatmap_id=beatmap.id,
            ruleset=ruleset,
            playstyle=Playstyle.VANILLA,
            category=LeaderboardCategory.GLOBAL,
        )

    async def _resolve_leaderboard_listing(
        self,
        *,
        request: GetscoresRequest | None,
        beatmap: Beatmap,
        user_id: int | None,
    ) -> tuple[tuple[GetscoresPersonalBest, ...], GetscoresPersonalBest | None]:
        base_scope = _leaderboard_scope_from_request(
            request=request,
            beatmap=beatmap,
        )
        if base_scope is None or self._leaderboards is None:
            return (), None

        viewer_context = await self._resolve_viewer_context(user_id)
        scope = await self._resolve_viewer_dependent_scope(
            scope=base_scope,
            user_id=user_id,
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
            user_id is not None
            and viewer_context is not None
            and viewer_context.leaderboard_visible
        ):
            personal_best_row = await self._leaderboards.get_personal_best(
                scope,
                viewer_user_id=user_id,
            )
            if personal_best_row is not None:
                personal_best = _leaderboard_row_to_getscores_row(personal_best_row)

        return tuple(_leaderboard_row_to_getscores_row(row) for row in rows), personal_best

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


def _unavailable(reason: GetscoresResolveReason) -> GetscoresResolveOutcome:
    """Build an unavailable outcome."""
    return GetscoresResolveOutcome(
        kind=GetscoresOutcomeKind.UNAVAILABLE,
        header=None,
        reason=reason,
    )


def _is_displayable_in_score_listing(beatmap: Beatmap) -> bool:
    """Return whether the beatmap can produce a score listing header."""
    return beatmap.effective_status in _DISPLAYABLE_STATUSES


def _is_leaderboard_visible_beatmap(beatmap: Beatmap) -> bool:
    return beatmap.effective_status in _LEADERBOARD_VISIBLE_STATUSES


def _ruleset_from_request(request: GetscoresRequest) -> Ruleset | None:
    if request.mode is None:
        return None
    try:
        return Ruleset(request.mode)
    except ValueError:
        return None


def _leaderboard_scope_from_request(
    *,
    request: GetscoresRequest | None,
    beatmap: Beatmap,
) -> LeaderboardReadScope | None:
    if request is None or request.song_select is True:
        return None

    ruleset = _ruleset_from_request(request)
    if ruleset is None or not _is_vanilla_request(request):
        return None

    category = _leaderboard_category_from_request(request)
    if category is None:
        return None

    mod_filter_key: int | None = None
    if category is LeaderboardCategory.SELECTED_MODS:
        filter_result = _selected_mod_filter_from_request(request)
        if filter_result is None or not filter_result.is_supported:
            return None
        mod_filter_key = filter_result.key

    return LeaderboardReadScope(
        beatmap_id=beatmap.id,
        beatmap_checksum=beatmap.checksum_md5,
        ruleset=ruleset,
        playstyle=Playstyle.VANILLA,
        category=category,
        mod_filter_key=mod_filter_key,
    )


def _leaderboard_category_from_request(
    request: GetscoresRequest,
) -> LeaderboardCategory | None:
    if request.leaderboard_type == _LOCAL_LEADERBOARD_TYPE:
        return LeaderboardCategory.GLOBAL
    if request.leaderboard_type == _SELECTED_MODS_LEADERBOARD_TYPE:
        return LeaderboardCategory.SELECTED_MODS
    if request.leaderboard_type == _FRIENDS_LEADERBOARD_TYPE:
        return LeaderboardCategory.FRIENDS
    if request.leaderboard_type == _COUNTRY_LEADERBOARD_TYPE:
        return LeaderboardCategory.COUNTRY
    return None


def _country_scope_filter(country: str) -> str | None:
    normalized = country.strip().upper()
    if normalized in {"", "XX"}:
        return None
    return normalized


def _is_vanilla_request(request: GetscoresRequest) -> bool:
    mods = _mods_from_request(request)
    if mods is None:
        return False
    return not (mods.has(Mod.RELAX) or mods.has(Mod.AUTOPILOT))


def _selected_mod_filter_from_request(
    request: GetscoresRequest,
) -> LeaderboardModFilter | None:
    mods = _mods_from_request(request)
    if mods is None:
        return None
    return filter_from_mod_combination(mods)


def _mods_from_request(request: GetscoresRequest) -> ModCombination | None:
    try:
        return ModCombination.from_bitmask(request.mods or 0)
    except ValueError:
        return None


def _leaderboard_row_to_getscores_row(
    row: BeatmapLeaderboardRow,
) -> GetscoresPersonalBest:
    return GetscoresPersonalBest(
        score_id=row.score_id,
        user_id=row.user_id,
        username=row.username,
        beatmap_id=row.beatmap_id,
        ruleset=row.ruleset,
        playstyle=row.playstyle,
        score=row.score,
        max_combo=row.max_combo,
        n50=row.hit_counts.n50,
        n100=row.hit_counts.n100,
        n300=row.hit_counts.n300,
        miss=row.hit_counts.miss,
        katu=row.hit_counts.katu,
        geki=row.hit_counts.geki,
        perfect=row.perfect,
        mods=row.displayed_mods.to_persistence_bitmask(),
        rank=row.rank,
        submitted_at=row.submitted_at,
        has_replay=row.has_replay,
    )
