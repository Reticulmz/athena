"""osu!direct検索projection用のdomain valueを定義するmodule."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Protocol

from osu_server.domain.beatmaps.models import (
    Beatmap,
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


@dataclass(slots=True, frozen=True)
class DirectSearchRequest:
    """osu!direct検索backendへ渡す検索入力を表す.

    Attributes:
        query_text (str): stable clientが指定した検索文字列.
        status (BeatmapRankStatus | None): direct status filter. 指定なしならNone.
        mode (BeatmapMode | None): stable mode filter. 指定なしならNone.
        page (int): 0始まりのpage番号.
        page_size (int): 1 pageあたりの候補数.
        listing (DirectSearchListing): text検索かspecial listingかを示す種別.
    """

    query_text: str
    status: BeatmapRankStatus | None = None
    mode: BeatmapMode | None = None
    page: int = 0
    page_size: int = 100
    listing: DirectSearchListing = DirectSearchListing.SEARCH

    def __post_init__(self) -> None:
        """Page入力の永続backend向け制約を検証する.

        Returns:
            None: page入力が使用可能であることを示す.

        Raises:
            ValueError: pageが負値,またはpage_sizeが正でない場合.
        """
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
    "DirectSearchBackend",
    "DirectSearchBackendResult",
    "DirectSearchCandidate",
    "DirectSearchListing",
    "DirectSearchRequest",
    "build_beatmapset_search_document",
]
