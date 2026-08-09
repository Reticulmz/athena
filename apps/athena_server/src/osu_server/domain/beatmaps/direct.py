"""osu!direct検索projection用のdomain valueを定義するmodule."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Protocol

from osu_server.domain.beatmaps.models import (
    Beatmap,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
)

_DIRECT_INACTIVE_STATUSES: Final = frozenset(
    {
        BeatmapRankStatus.GRAVEYARD,
        BeatmapRankStatus.NOT_SUBMITTED,
        BeatmapRankStatus.UNKNOWN,
    }
)


class DirectSearchListing(StrEnum):
    """Stable osu!direct検索のlisting種別を表す.

    Attributes:
        SEARCH (DirectSearchListing): 通常のtext検索または空queryのcatalog listing.
        NEWEST (DirectSearchListing): `Newest` special queryから導出するlisting.
        TOP_RATED (DirectSearchListing): rating実装までfallback順で返すspecial listing.
        MOST_PLAYED (DirectSearchListing): playcount ranking実装までfallback順で返す
            special listing.
    """

    SEARCH = "search"
    NEWEST = "newest"
    TOP_RATED = "top_rated"
    MOST_PLAYED = "most_played"


class DirectAccessPolicyMode(StrEnum):
    """osu!direct access policyの設定値を表す.

    Attributes:
        AUTHENTICATED (DirectAccessPolicyMode): 認証済みstable userを許可する既定policy.
        DISABLED (DirectAccessPolicyMode): osu!direct accessを全認証済みuserへ拒否するpolicy.
        SUPPORTER_ENTITLEMENT (DirectAccessPolicyMode): supporter権利を要求する予約policy.
    """

    AUTHENTICATED = "authenticated"
    DISABLED = "disabled"
    SUPPORTER_ENTITLEMENT = "supporter_entitlement"


class DirectAccessDecision(StrEnum):
    """osu!direct access policyの判定結果を表す.

    Attributes:
        ALLOWED (DirectAccessDecision): osu!direct workを開始してよい状態.
        AUTHENTICATION_REQUIRED (DirectAccessDecision): stable legacy認証が必要な状態.
        DENIED (DirectAccessDecision): 認証済みだがpolicyにより拒否する状態.
    """

    ALLOWED = "allowed"
    AUTHENTICATION_REQUIRED = "authentication_required"
    DENIED = "denied"


@dataclass(slots=True, frozen=True)
class DirectAccessPolicy:
    """osu!direct access可否をsearch rankingやcoverageから分離して判定する.

    Attributes:
        mode (DirectAccessPolicyMode): deploymentが選んだaccess policy.
    """

    mode: DirectAccessPolicyMode

    def evaluate(
        self,
        *,
        authenticated_user_id: int | None,
        has_supporter_entitlement: bool = False,
    ) -> DirectAccessDecision:
        """認証状態とpolicy設定からosu!direct access decisionを返す.

        Args:
            authenticated_user_id (int | None): legacy認証で解決したuser ID.
            has_supporter_entitlement (bool): supporter_entitlement policyを満たすか.

        Returns:
            DirectAccessDecision: handlerがwork開始前に適用するaccess decision.
        """
        if authenticated_user_id is None:
            return DirectAccessDecision.AUTHENTICATION_REQUIRED
        if self.mode is DirectAccessPolicyMode.DISABLED:
            return DirectAccessDecision.DENIED
        if (
            self.mode is DirectAccessPolicyMode.SUPPORTER_ENTITLEMENT
            and not has_supporter_entitlement
        ):
            return DirectAccessDecision.DENIED
        return DirectAccessDecision.ALLOWED


class DirectExternalIndexBackend(StrEnum):
    """osu!direct external index backendの閉集合を表す.

    Attributes:
        MEILISEARCH (DirectExternalIndexBackend): Meilisearch backendを示す値.
    """

    MEILISEARCH = "meilisearch"


class DirectExternalIndexStatus(StrEnum):
    """osu!direct external index document同期状態を表す.

    Attributes:
        PENDING (DirectExternalIndexStatus): 同期が未完了または再試行待ちである状態.
        SUCCEEDED (DirectExternalIndexStatus): 対象versionの同期に成功した状態.
        FAILED (DirectExternalIndexStatus): 対象versionの同期に失敗した状態.
    """

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DirectCoverageKind(StrEnum):
    """osu!direct catalog coverage recordの種別を表す.

    Attributes:
        FEED_WINDOW (DirectCoverageKind): feed window観測によるcoverage.
        ID_RANGE (DirectCoverageKind): explicit id range crawlによるcoverage.
    """

    FEED_WINDOW = "feed_window"
    ID_RANGE = "id_range"


class DirectCoverageStatusScope(StrEnum):
    """osu!direct catalog coverage recordのstatus scopeを表す.

    Attributes:
        ALL (DirectCoverageStatusScope): 全statusを対象にするscope.
        RANKED (DirectCoverageStatusScope): rankedのみを対象にするscope.
        APPROVED (DirectCoverageStatusScope): approvedのみを対象にするscope.
        LOVED (DirectCoverageStatusScope): lovedのみを対象にするscope.
        QUALIFIED (DirectCoverageStatusScope): qualifiedのみを対象にするscope.
        PENDING (DirectCoverageStatusScope): pendingのみを対象にするscope.
        WIP (DirectCoverageStatusScope): work in progressのみを対象にするscope.
        GRAVEYARD (DirectCoverageStatusScope): graveyardのみを対象にするscope.
        NOT_SUBMITTED (DirectCoverageStatusScope): not submittedのみを対象にするscope.
        UNKNOWN (DirectCoverageStatusScope): unknownのみを対象にするscope.
    """

    ALL = "all"
    RANKED = "ranked"
    APPROVED = "approved"
    LOVED = "loved"
    QUALIFIED = "qualified"
    PENDING = "pending"
    WIP = "wip"
    GRAVEYARD = "graveyard"
    NOT_SUBMITTED = "not_submitted"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class DirectSearchRequest:
    """osu!direct検索backendへ渡す検索入力を表す.

    Attributes:
        authenticated_user_id (int): stable legacy認証で解決したuser ID.
        query_text (str): stable clientが指定した検索文字列.
        statuses (tuple[BeatmapRankStatus, ...]): direct status filter. 空なら全status.
        mode (BeatmapMode | None): stable mode filter. 指定なしならNone.
        page (int): 0始まりのpage番号.
        page_size (int): 1 pageあたりの候補数.
        listing (DirectSearchListing): text検索かspecial listingかを示す種別.
    """

    authenticated_user_id: int
    query_text: str
    statuses: tuple[BeatmapRankStatus, ...] = ()
    mode: BeatmapMode | None = None
    page: int = 0
    page_size: int = 100
    listing: DirectSearchListing = DirectSearchListing.SEARCH

    def __post_init__(self) -> None:
        """Page入力の永続backend向け制約を検証する.

        Returns:
            None: page入力が使用可能であることを示す.

        Raises:
            ValueError: user IDが正でない場合, pageが負値,またはpage_sizeが正でない場合.
        """
        if self.authenticated_user_id <= 0:
            msg = "authenticated_user_id must be positive"
            raise ValueError(msg)
        if self.page < 0:
            msg = "page must not be negative"
            raise ValueError(msg)
        if self.page_size <= 0:
            msg = "page_size must be positive"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class DirectSearchCandidate:
    """Search backendが返すbeatmapset候補を表す.

    Attributes:
        beatmapset_id (int): hydration対象にするbeatmapset ID.
        score (float): backendが計算したranking score. fallback listingでは0.0を使う.
    """

    beatmapset_id: int
    score: float


@dataclass(slots=True, frozen=True)
class DirectSearchBackendResult:
    """Search backendの候補結果を表す.

    Attributes:
        candidates (tuple[DirectSearchCandidate, ...]): page内に返す候補列.
        has_more (bool): page_sizeを超える候補がある場合はTrue.
    """

    candidates: tuple[DirectSearchCandidate, ...]
    has_more: bool


class DirectSearchBackend(Protocol):
    """osu!direct検索backendのservice-facing contractを表す."""

    async def search(self, request: DirectSearchRequest) -> DirectSearchBackendResult:
        """検索入力からbeatmapset候補を返す.

        Args:
            request (DirectSearchRequest): stable inputから導出されたbackend検索条件.

        Returns:
            DirectSearchBackendResult: hydration前の候補IDとscore.
        """
        ...

    async def validate(self) -> None:
        """Backendが検索trafficを受けられる状態か検証する.

        Returns:
            None: backend capabilityが揃っていることを示す.
        """
        ...


@dataclass(slots=True, frozen=True)
class BeatmapSetSearchDocument:
    """osu!direct検索backendへ渡すbeatmapset単位のprojectionを表す.

    Attributes:
        beatmapset_id (int): projection対象のbeatmapset ID.
        artist (str): 検索対象のartist名.
        title (str): 検索対象の曲名.
        creator (str): 検索対象のmapper名.
        artist_unicode (str | None): Unicode artist名. 未提供ならNone.
        title_unicode (str | None): Unicode title. 未提供ならNone.
        source (str): upstream source検索文字列. 未提供なら空文字列.
        tags (str): upstream tags検索文字列. 未提供なら空文字列.
        difficulty_names (str): child difficulty名を空白で結合した検索文字列.
        modes (tuple[BeatmapMode, ...]): child beatmapが持つmodeの閉集合.
        status (BeatmapRankStatus): direct検索で扱うbeatmapset status.
        last_update_at (datetime | None): child metadataの最新更新時刻. 未提供ならNone.
        is_active (bool): 検索対象として有効ならTrue.
        document_version (int): projection内容が変わるたびに進むversion.
        updated_at (datetime): projectionを最後に更新したUTC timestamp.
    """

    beatmapset_id: int
    artist: str
    title: str
    creator: str
    artist_unicode: str | None
    title_unicode: str | None
    source: str
    tags: str
    difficulty_names: str
    modes: tuple[BeatmapMode, ...]
    status: BeatmapRankStatus
    last_update_at: datetime | None
    is_active: bool
    document_version: int
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class DirectExternalIndexState:
    """osu!direct external index documentのretry可能な同期状態を表す.

    Attributes:
        backend (DirectExternalIndexBackend): 状態を記録するexternal index backend.
        beatmapset_id (int): 同期対象のbeatmapset ID.
        document_version (int): 同期を試行したprojection version.
        status (DirectExternalIndexStatus): 同期結果または再試行待ち状態.
        last_attempted_at (datetime | None): 最後に同期を試行したUTC timestamp.
        last_succeeded_at (datetime | None): 最後に同期へ成功したUTC timestamp.
        failure_reason (str | None): 失敗時のsanitized reason. 成功時はNone.
    """

    backend: DirectExternalIndexBackend
    beatmapset_id: int
    document_version: int
    status: DirectExternalIndexStatus
    last_attempted_at: datetime | None
    last_succeeded_at: datetime | None
    failure_reason: str | None

    def __post_init__(self) -> None:
        """External index stateの永続化前制約を検証する.

        Returns:
            None: stateが永続化可能な値であることを示す.

        Raises:
            ValueError: beatmapset_idまたはdocument_versionが正でない場合.
        """
        if self.beatmapset_id <= 0:
            msg = "beatmapset_id must be positive"
            raise ValueError(msg)
        if self.document_version <= 0:
            msg = "document_version must be positive"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class DirectCoverageRecord:
    """osu!direct catalog syncの観測または失敗状態を表す.

    Attributes:
        coverage_kind (DirectCoverageKind): feed windowかid range crawlかを示す種別.
        source (BeatmapMetadataSource): coverageを記録したmetadata source.
        status_scope (DirectCoverageStatusScope): 同期対象status scope.
        sort_key (str): feed sortまたはcrawl sortの識別子.
        window_key (str): cursor, page, window identifierを保存する識別子.
        from_beatmapset_id (int): 観測またはcrawlした範囲開始ID.
        to_beatmapset_id (int): 観測またはcrawlした範囲終了ID.
        cursor (str | None): upstream cursorまたはpage marker.
        completed_at (datetime | None): 完了時刻. success時のみ値を持つ.
        failed_at (datetime | None): 失敗時刻. failure時のみ値を持つ.
        failure_reason (str | None): sanitized operational reason. failure時のみ値を持つ.
    """

    coverage_kind: DirectCoverageKind
    source: BeatmapMetadataSource
    status_scope: DirectCoverageStatusScope
    sort_key: str
    window_key: str
    from_beatmapset_id: int
    to_beatmapset_id: int
    cursor: str | None
    completed_at: datetime | None
    failed_at: datetime | None
    failure_reason: str | None

    def __post_init__(self) -> None:
        """Coverage recordの不変条件を検証する.

        Returns:
            None: positive rangeとtimestamp exclusivityを検証して完了する.

        Raises:
            ValueError: rangeが負値または順序不正の場合,もしくは成功/失敗時刻が両方ある場合.
        """
        if self.from_beatmapset_id < 0:
            msg = "from_beatmapset_id must not be negative"
            raise ValueError(msg)
        if self.to_beatmapset_id < 0:
            msg = "to_beatmapset_id must not be negative"
            raise ValueError(msg)
        if self.to_beatmapset_id < self.from_beatmapset_id:
            msg = "to_beatmapset_id must not be less than from_beatmapset_id"
            raise ValueError(msg)
        if self.completed_at is not None and self.failed_at is not None:
            msg = "completed_at and failed_at must not both be set"
            raise ValueError(msg)


def build_beatmapset_search_document(
    beatmapset: BeatmapSet,
    *,
    previous: BeatmapSetSearchDocument | None = None,
    updated_at: datetime | None = None,
) -> BeatmapSetSearchDocument:
    """Beatmapset metadataからosu!direct検索projectionを構築する.

    Args:
        beatmapset (BeatmapSet): metadata保存pathが永続化するbeatmapset snapshot.
        previous (BeatmapSetSearchDocument | None): 既存projection. 未登録ならNone.
        updated_at (datetime | None): projection変更時に記録するUTC時刻. Noneなら現在時刻.

    Returns:
        BeatmapSetSearchDocument: activeまたはinactiveな検索projection.

    Notes:
        `source`と`tags`はdomain metadataへまだ存在しないため空文字列を保存する.
    """
    now = updated_at or datetime.now(UTC)
    document = BeatmapSetSearchDocument(
        beatmapset_id=beatmapset.id,
        artist=beatmapset.artist,
        title=beatmapset.title,
        creator=beatmapset.creator,
        artist_unicode=beatmapset.artist_unicode,
        title_unicode=beatmapset.title_unicode,
        source="",
        tags="",
        difficulty_names=_difficulty_names(beatmapset.beatmaps),
        modes=_document_modes(beatmapset.beatmaps),
        status=beatmapset.official_status,
        last_update_at=_last_update_at(beatmapset.beatmaps),
        is_active=_is_active_direct_beatmapset(beatmapset),
        document_version=previous.document_version if previous is not None else 1,
        updated_at=previous.updated_at if previous is not None else now,
    )
    if previous is None or _document_content_changed(previous, document):
        return replace(
            document,
            document_version=1 if previous is None else previous.document_version + 1,
            updated_at=now,
        )
    return document


def _is_active_direct_beatmapset(beatmapset: BeatmapSet) -> bool:
    """Beatmapsetがosu!direct検索対象としてactiveか判定する.

    Args:
        beatmapset (BeatmapSet): statusとchildを評価するbeatmapset.

    Returns:
        bool: active statusかつusable childを1件以上持つ場合はTrue.
    """
    return (
        beatmapset.official_status not in _DIRECT_INACTIVE_STATUSES
        and len(_usable_beatmaps(beatmapset.beatmaps)) > 0
    )


def _usable_beatmaps(beatmaps: tuple[Beatmap, ...]) -> tuple[Beatmap, ...]:
    """osu!direct検索documentに使えるchild beatmapだけを返す.

    Args:
        beatmaps (tuple[Beatmap, ...]): beatmapsetに属するchild beatmap列.

    Returns:
        tuple[Beatmap, ...]: inactive statusを除いたchild beatmap列.
    """
    return tuple(
        beatmap
        for beatmap in beatmaps
        if beatmap.effective_status not in _DIRECT_INACTIVE_STATUSES
    )


def _document_beatmaps(beatmaps: tuple[Beatmap, ...]) -> tuple[Beatmap, ...]:
    """検索fieldへ使うchild beatmap列を返す.

    Args:
        beatmaps (tuple[Beatmap, ...]): beatmapsetに属するchild beatmap列.

    Returns:
        tuple[Beatmap, ...]: usable childがあればそれらを返し, なければ元のchild列を返す.
    """
    usable = _usable_beatmaps(beatmaps)
    return usable or beatmaps


def _difficulty_names(beatmaps: tuple[Beatmap, ...]) -> str:
    """Child difficulty名を検索用文字列へ変換する.

    Args:
        beatmaps (tuple[Beatmap, ...]): difficulty名を抽出するchild beatmap列.

    Returns:
        str: difficulty versionを空白区切りで結合した文字列. childがなければ空文字列.
    """
    return " ".join(beatmap.version for beatmap in _document_beatmaps(beatmaps))


def _document_modes(beatmaps: tuple[Beatmap, ...]) -> tuple[BeatmapMode, ...]:
    """Child beatmap modeをprojection保存用の閉集合へ変換する.

    Args:
        beatmaps (tuple[Beatmap, ...]): modeを抽出するchild beatmap列.

    Returns:
        tuple[BeatmapMode, ...]: mode value順の重複なしmode列. childがなければUNKNOWNだけを返す.
    """
    modes = {beatmap.mode for beatmap in _document_beatmaps(beatmaps)}
    if not modes:
        return (BeatmapMode.UNKNOWN,)
    return tuple(sorted(modes, key=lambda mode: mode.value))


def _last_update_at(beatmaps: tuple[Beatmap, ...]) -> datetime | None:
    """Child metadataが持つ最新のofficial更新時刻を返す.

    Args:
        beatmaps (tuple[Beatmap, ...]): 更新時刻を抽出するchild beatmap列.

    Returns:
        datetime | None: 最大のofficial_last_updated_at. どのchildにもなければNone.
    """
    values = [
        beatmap.official_last_updated_at
        for beatmap in beatmaps
        if beatmap.official_last_updated_at is not None
    ]
    return max(values) if values else None


def _document_content_changed(
    previous: BeatmapSetSearchDocument,
    current: BeatmapSetSearchDocument,
) -> bool:
    """Version対象fieldが既存documentから変わったか判定する.

    Args:
        previous (BeatmapSetSearchDocument): 保存済みprojection.
        current (BeatmapSetSearchDocument): metadataから再構築したprojection.

    Returns:
        bool: document_versionとupdated_at以外のfieldが変わっていればTrue.
    """
    return (
        previous.beatmapset_id != current.beatmapset_id
        or previous.artist != current.artist
        or previous.title != current.title
        or previous.creator != current.creator
        or previous.artist_unicode != current.artist_unicode
        or previous.title_unicode != current.title_unicode
        or previous.source != current.source
        or previous.tags != current.tags
        or previous.difficulty_names != current.difficulty_names
        or previous.modes != current.modes
        or previous.status is not current.status
        or previous.last_update_at != current.last_update_at
        or previous.is_active is not current.is_active
    )


__all__ = [
    "BeatmapSetSearchDocument",
    "DirectAccessDecision",
    "DirectAccessPolicy",
    "DirectAccessPolicyMode",
    "DirectCoverageKind",
    "DirectCoverageRecord",
    "DirectCoverageStatusScope",
    "DirectExternalIndexBackend",
    "DirectExternalIndexState",
    "DirectExternalIndexStatus",
    "DirectSearchBackend",
    "DirectSearchBackendResult",
    "DirectSearchCandidate",
    "DirectSearchListing",
    "DirectSearchRequest",
    "build_beatmapset_search_document",
]
