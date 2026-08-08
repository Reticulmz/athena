"""Beatmap leaderboard query use-case を提供する.

Stable transport の request や row 型を持ち込まずに, beatmap の表示可否と leaderboard
listing を読み取り専用で解決する.
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
    """Viewer の leaderboard 表示可否を判定する権限読み取り Protocol.

    実装は User ID に対応する現在の権限だけを返し, query workflow を変更しない.
    """

    async def compute_permissions(self, user_id: int) -> Privileges:
        """指定 User の現在の権限を計算する.

        Args:
            user_id (int): 権限を計算する User ID.

        Returns:
            Privileges: leaderboard 表示可否の判定に使う権限集合.
        """
        ...


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
    """Beatmap leaderboard 解決結果の client-visible な種別を表す.

    Attributes:
        HEADER (BeatmapLeaderboardOutcomeKind): beatmap header を返せる結果.
        UNAVAILABLE (BeatmapLeaderboardOutcomeKind): beatmap を表示できない結果.
        UPDATE_AVAILABLE (BeatmapLeaderboardOutcomeKind): client の譜面が古いことを示す結果.
    """

    HEADER = "header"
    UNAVAILABLE = "unavailable"
    UPDATE_AVAILABLE = "update_available"


class BeatmapLeaderboardResolveReason(Enum):
    """Beatmap leaderboard の解決経路または利用不可理由を表す.

    Attributes:
        KNOWN_CHECKSUM (BeatmapLeaderboardResolveReason): checksum で既知 beatmap を見つけた.
        KNOWN_FILENAME_IN_SET (BeatmapLeaderboardResolveReason): beatmapset 内の filename で
            beatmap を見つけた.
        NOT_SUBMITTED (BeatmapLeaderboardResolveReason): score listing で表示できない status.
        NOT_FOUND (BeatmapLeaderboardResolveReason): beatmap または関連 beatmapset がない.
        PENDING_FETCH (BeatmapLeaderboardResolveReason): metadata fetch が進行中.
        FAILED_METADATA (BeatmapLeaderboardResolveReason): metadata fetch が失敗した.
        UPDATE_AVAILABLE (BeatmapLeaderboardResolveReason): 同名の server beatmap が client の
            checksum と異なる.
    """

    KNOWN_CHECKSUM = "known_checksum"
    KNOWN_FILENAME_IN_SET = "known_filename_in_set"
    NOT_SUBMITTED = "not_submitted"
    NOT_FOUND = "not_found"
    PENDING_FETCH = "pending_fetch"
    FAILED_METADATA = "failed_metadata"
    UPDATE_AVAILABLE = "update_available"


@dataclass(slots=True, frozen=True)
class BeatmapLeaderboardRequest:
    """Beatmap leaderboard を解決する transport-neutral な読み取り要求を表す.

    Attributes:
        beatmap_checksum (str | None): client が送った beatmap の MD5 checksum.
        filename (str | None): beatmapset 内で照合する beatmap filename.
        beatmapset_id_hint (int | None): filename 照合に使う beatmapset ID.
        viewer_user_id (int | None): personal best と viewer 依存 scope の User ID.
        ruleset (Ruleset | None): leaderboard を読む score ruleset.
        playstyle (Playstyle): leaderboard を読む playstyle.
        category (LeaderboardCategory | None): leaderboard の表示 category.
        selected_mods (ModCombination | None): SELECTED_MODS category の ModCombination.
        header_only (bool): True の場合は score rows を要求しない.
    """

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
    """Beatmap leaderboard response に含める beatmap header を表す.

    Attributes:
        beatmap (Beatmap): 解決した beatmap.
        beatmapset (BeatmapSet): beatmap が属する beatmapset.
    """

    beatmap: Beatmap
    beatmapset: BeatmapSet


@dataclass(slots=True, frozen=True)
class BeatmapLeaderboardResult:
    """Beatmap leaderboard query の解決結果を表す.

    Attributes:
        kind (BeatmapLeaderboardOutcomeKind): client-visible な解決結果の種別.
        header (BeatmapLeaderboardHeader | None): 表示可能な beatmap header. 利用不可時は None.
        personal_best (BeatmapLeaderboardRow | None): viewer の personal best row.
        rows (tuple[BeatmapLeaderboardRow, ...]): 表示する最大 50 件の leaderboard rows.
        reason (BeatmapLeaderboardResolveReason): 解決経路または利用不可理由.
    """

    kind: BeatmapLeaderboardOutcomeKind
    header: BeatmapLeaderboardHeader | None
    personal_best: BeatmapLeaderboardRow | None
    rows: tuple[BeatmapLeaderboardRow, ...]
    reason: BeatmapLeaderboardResolveReason


@dataclass(slots=True, frozen=True)
class BeatmapPersonalBestRankQueryInput:
    """Beatmap personal best rank を読むための入力を表す.

    Attributes:
        user_id (int): 対象 User ID.
        beatmap_id (int): 対象 Beatmap ID.
        beatmap_checksum (str): 現在の Beatmap checksum.
        ruleset (Ruleset): 対象 ruleset.
        playstyle (Playstyle): 対象 playstyle.
        category (LeaderboardCategory): 順位を評価する category.
        selected_mods (ModCombination | None): SELECTED_MODS category で評価する mods.
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
    """Beatmap personal best rank の読み取り結果を表す.

    Attributes:
        rank (int | None): 現在の順位. 対象 score がない場合は None.
    """

    rank: int | None


@dataclass(slots=True, frozen=True)
class _ViewerLeaderboardContext:
    """Viewer 依存 leaderboard scope の解決に必要な内部情報を表す.

    Attributes:
        country (str): COUNTRY category の絞り込みに使う User の国コード.
        leaderboard_visible (bool): viewer 自身の personal best を返せるかどうか.
    """

    country: str
    leaderboard_visible: bool


class BeatmapPersonalBestRankQuery:
    """Source scores から User の現在の beatmap personal best 順位を読む.

    Attributes:
        _leaderboards (BeatmapLeaderboardQueryRepository): personal best row を読む
            query repository.
    """

    _leaderboards: BeatmapLeaderboardQueryRepository

    def __init__(self, leaderboards: BeatmapLeaderboardQueryRepository) -> None:
        """Personal best row を読む repository を設定する.

        Args:
            leaderboards (BeatmapLeaderboardQueryRepository): 読み取り専用の leaderboard
                query repository.
        """
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
    """Transport に依存せず beatmap leaderboard listing を解決する.

    Attributes:
        _repository (BeatmapScoreListingQueryRepository): beatmap, beatmapset, fetch state を
            読む query repository.
        _leaderboards (BeatmapLeaderboardQueryRepository): leaderboard rows と personal best を
            読む query repository.
        _user_repository (UserQueryRepository | None): viewer の country を読む repository.
        _permission_service (_PermissionReader | None): viewer の表示権限を計算する reader.
        _friend_eligible_user_ids_query (GetFriendEligibleUserIdsQueryUseCase | None): FRIENDS
            category の対象 User ID を読む query.
    """

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
        """Beatmap listing と viewer scope を解決する collaborators を設定する.

        Args:
            repository (BeatmapScoreListingQueryRepository): beatmap, beatmapset, fetch state を
                読む repository.
            leaderboards (BeatmapLeaderboardQueryRepository): score rows と personal best を
                読む repository.
            user_repository (UserQueryRepository | None): viewer の country を読む repository.
            permission_service (_PermissionReader | None): viewer の leaderboard 表示可否を
                計算する reader.
            friend_eligible_user_ids_query (GetFriendEligibleUserIdsQueryUseCase | None):
                FRIENDS category の対象 User ID を返す query.
        """
        self._repository = repository
        self._leaderboards = leaderboards
        self._user_repository = user_repository
        self._permission_service = permission_service
        self._friend_eligible_user_ids_query = friend_eligible_user_ids_query

    async def execute(self, request: BeatmapLeaderboardRequest) -> BeatmapLeaderboardResult:
        """Beatmap leaderboard 要求を command-side mutation なしで解決する.

        Args:
            request (BeatmapLeaderboardRequest): checksum または beatmapset 内 filename を
                含む leaderboard 要求.

        Returns:
            BeatmapLeaderboardResult: header, update notification, または利用不可を表す結果.

        Notes:
            checksum の既知 beatmap を優先する. checksum miss では同名 beatmap の update を
            検出し, 見つからなければ metadata fetch state を利用する.
        """
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
        """未知 checksum の metadata fetch state から利用不可結果を作る.

        Args:
            checksum_md5 (str): 見つからなかった beatmap の MD5 checksum.

        Returns:
            BeatmapLeaderboardResult: fetch の進行中, 失敗, または未発見を表す利用不可結果.
        """
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
        """Beatmapset 内の filename で beatmap を解決する.

        Args:
            beatmapset_id (int): 照合する beatmapset の ID.
            filename (str): beatmapset 内で照合する filename.
            request (BeatmapLeaderboardRequest): header と leaderboard を解決する要求.

        Returns:
            BeatmapLeaderboardResult: 一致した beatmap の結果, または未発見の利用不可結果.
        """
        match = await self._find_by_filename_in_beatmapset(
            beatmapset_id,
            filename,
        )

        if match is None:
            return _unavailable(BeatmapLeaderboardResolveReason.NOT_FOUND)

        beatmap, beatmapset = match
        return await self._evaluate_beatmap(
            beatmap,
            reason=BeatmapLeaderboardResolveReason.KNOWN_FILENAME_IN_SET,
            request=request,
            beatmapset=beatmapset,
        )

    async def _evaluate_beatmap(
        self,
        beatmap: Beatmap,
        *,
        reason: BeatmapLeaderboardResolveReason,
        request: BeatmapLeaderboardRequest,
        beatmapset: BeatmapSet | None = None,
    ) -> BeatmapLeaderboardResult:
        """解決済み beatmap の表示可否, header, leaderboard を評価する.

        Args:
            beatmap (Beatmap): 評価する解決済み beatmap.
            reason (BeatmapLeaderboardResolveReason): beatmap を解決した経路.
            request (BeatmapLeaderboardRequest): listing scope を決める要求.
            beatmapset (BeatmapSet | None): すでに読み取った beatmapset. 未指定時は
                repository から取得する.

        Returns:
            BeatmapLeaderboardResult: header と必要に応じた rows を含む結果. beatmapset がないか
                score listing 非表示なら利用不可結果.
        """
        if beatmapset is None:
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
        """同名 beatmap の checksum 差異から update available を解決する.

        Args:
            checksum_md5 (str): client が送った beatmap の MD5 checksum.
            beatmapset_id (int): filename を照合する beatmapset の ID.
            filename (str): beatmapset 内で照合する filename.
            request (BeatmapLeaderboardRequest): checksum が一致した場合に再利用する要求.

        Returns:
            BeatmapLeaderboardResult: checksum が異なる表示可能 beatmap なら update available.
                checksum 一致時は通常の listing 結果, それ以外は利用不可結果.
        """
        match = await self._find_by_filename_in_beatmapset(
            beatmapset_id,
            filename,
        )
        if match is None:
            return _unavailable(BeatmapLeaderboardResolveReason.NOT_FOUND)

        beatmap, beatmapset = match
        if beatmap.checksum_md5 == checksum_md5:
            return await self._evaluate_beatmap(
                beatmap,
                reason=BeatmapLeaderboardResolveReason.KNOWN_FILENAME_IN_SET,
                request=request,
                beatmapset=beatmapset,
            )

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

    async def _find_by_filename_in_beatmapset(
        self,
        beatmapset_id: int,
        filename: str,
    ) -> tuple[Beatmap, BeatmapSet] | None:
        """Attachmentまたはmetadata由来のstable filenameでbeatmapとbeatmapsetを検索する.

        Args:
            beatmapset_id (int): 検索するbeatmapset ID.
            filename (str): stable clientが送ったbeatmap filename.

        Returns:
            tuple[Beatmap, BeatmapSet] | None: filenameに一致するbeatmapとbeatmapset.
                見つからない場合はNone.
        """
        beatmap = await self._repository.find_by_filename_in_beatmapset(
            beatmapset_id,
            filename,
        )
        if beatmap is not None:
            beatmapset = await self._repository.get_beatmapset(beatmap.beatmapset_id)
            if beatmapset is None:
                return None
            return beatmap, beatmapset

        beatmapset = await self._repository.get_beatmapset(beatmapset_id)
        if beatmapset is None:
            return None
        beatmap = _beatmap_by_stable_filename(beatmapset, filename)
        if beatmap is None:
            return None
        return beatmap, beatmapset

    async def _resolve_leaderboard_listing(
        self,
        *,
        request: BeatmapLeaderboardRequest,
        beatmap: Beatmap,
    ) -> tuple[tuple[BeatmapLeaderboardRow, ...], BeatmapLeaderboardRow | None]:
        """Beatmap と viewer の scope に一致する leaderboard rows を読む.

        Args:
            request (BeatmapLeaderboardRequest): category, ruleset, viewer を含む要求.
            beatmap (Beatmap): leaderboard scope を作る表示可能 beatmap.

        Returns:
            tuple[tuple[BeatmapLeaderboardRow, ...], BeatmapLeaderboardRow | None]: top rows と
                viewer の personal best. scope を作れない場合は空 rows と None.
        """
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
        """Viewer の country と leaderboard 表示可否を読み取る.

        Args:
            user_id (int | None): context を読む viewer の User ID.

        Returns:
            _ViewerLeaderboardContext | None: 解決した viewer context. User ID, repository,
                または User がない場合は None.
        """
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
        """Category に応じて viewer 依存の leaderboard scope を補完する.

        Args:
            scope (LeaderboardReadScope): beatmap と score mode で作成済みの基本 scope.
            user_id (int | None): FRIENDS category の viewer User ID.
            viewer_context (_ViewerLeaderboardContext | None): COUNTRY と personal best の
                判定に使う viewer context.

        Returns:
            LeaderboardReadScope | None: COUNTRY または FRIENDS の絞り込みを加えた scope.
                必要な viewer 情報がない場合は None.
        """
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
    """Header を返せない leaderboard 解決結果を作る.

    Args:
        reason (BeatmapLeaderboardResolveReason): 利用不可になった理由.

    Returns:
        BeatmapLeaderboardResult: header, personal best, rows を持たない利用不可結果.
    """
    return BeatmapLeaderboardResult(
        kind=BeatmapLeaderboardOutcomeKind.UNAVAILABLE,
        header=None,
        personal_best=None,
        rows=(),
        reason=reason,
    )


def _is_displayable_in_score_listing(beatmap: Beatmap) -> bool:
    """Beatmap が score listing の header として表示可能かを判定する.

    Args:
        beatmap (Beatmap): status を評価する beatmap.

    Returns:
        bool: effective status が score listing 対象なら True.
    """
    return beatmap.effective_status in _DISPLAYABLE_STATUSES


def _is_leaderboard_visible_beatmap(beatmap: Beatmap) -> bool:
    """Beatmap が leaderboard score rows を表示可能かを判定する.

    Args:
        beatmap (Beatmap): status を評価する beatmap.

    Returns:
        bool: effective status が leaderboard rows 対象なら True.
    """
    return beatmap.effective_status in _LEADERBOARD_VISIBLE_STATUSES


def _beatmap_by_stable_filename(beatmapset: BeatmapSet, filename: str) -> Beatmap | None:
    """Metadataから復元できるstable filenameに一致するbeatmapを返す.

    Args:
        beatmapset (BeatmapSet): metadata fetchで保存済みのbeatmapset.
        filename (str): stable clientが送ったbeatmap filename.

    Returns:
        Beatmap | None: 一致するbeatmap. 見つからない場合はNone.
    """
    for beatmap in beatmapset.beatmaps:
        if _stable_beatmap_filename(beatmapset, beatmap) == filename:
            return beatmap
    return None


def _stable_beatmap_filename(beatmapset: BeatmapSet, beatmap: Beatmap) -> str:
    """Stable clientの通常beatmap filenameをmetadataから復元する.

    Args:
        beatmapset (BeatmapSet): artist, title, creatorを持つbeatmapset.
        beatmap (Beatmap): difficulty versionを持つbeatmap.

    Returns:
        str: `Artist - Title (Creator) [Version].osu`形式のfilename.
    """
    return (
        f"{beatmapset.artist} - {beatmapset.title} ({beatmapset.creator}) [{beatmap.version}].osu"
    )


def _leaderboard_scope_from_request(
    *,
    request: BeatmapLeaderboardRequest,
    beatmap: Beatmap,
) -> LeaderboardReadScope | None:
    """Request と beatmap から score leaderboard の基本 scope を作る.

    Args:
        request (BeatmapLeaderboardRequest): score mode, category, selected mods を含む要求.
        beatmap (Beatmap): scope に ID と checksum を与える表示可能 beatmap.

    Returns:
        LeaderboardReadScope | None: vanilla score listing の有効な scope. header-only,
            未対応 playstyle, 未指定 category, 不完全な SELECTED_MODS では None.
    """
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
    """Country category に使用できる ISO 風国コードへ正規化する.

    Args:
        country (str): User に保存された国コード.

    Returns:
        str | None: 前後空白を除き大文字化した国コード. 空文字列または XX では None.
    """
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
