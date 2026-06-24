"""beatmap の公開状態、鮮度、取得対象を表す domain model。

公式 rank status、operator のローカル上書き、metadata/file の鮮度、
leaderboard eligibility がここで同じ語彙として扱われる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime, timedelta

_MD5_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class BeatmapRankStatus(Enum):
    """外部 metadata が示す公式の beatmap 公開状態。"""

    RANKED = "ranked"
    APPROVED = "approved"
    LOVED = "loved"
    QUALIFIED = "qualified"
    PENDING = "pending"
    WIP = "wip"
    GRAVEYARD = "graveyard"
    NOT_SUBMITTED = "not_submitted"
    UNKNOWN = "unknown"


class LocalBeatmapStatus(Enum):
    """Athena operator が上書きできるローカルの beatmap 公開状態。"""

    RANKED = "ranked"
    LOVED = "loved"
    QUALIFIED = "qualified"
    PENDING = "pending"
    WIP = "wip"
    GRAVEYARD = "graveyard"
    NOT_SUBMITTED = "not_submitted"
    UNKNOWN = "unknown"


class BeatmapMetadataSource(Enum):
    """beatmap metadata の取得元。"""

    OFFICIAL = "official"
    LEGACY_OFFICIAL = "legacy_official"
    MIRROR = "mirror"


class BeatmapSourceVerification(Enum):
    """metadata source を公式情報として信頼できるか。"""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class BeatmapFetchState(Enum):
    """beatmap metadata fetch の状態。"""

    FRESH = "fresh"
    STALE = "stale"
    PENDING_FETCH = "pending_fetch"
    FAILED = "failed"


class BeatmapFileState(Enum):
    """osu file attachment の取得状態。"""

    AVAILABLE = "available"
    PENDING_FETCH = "pending_fetch"
    MISSING = "missing"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class BeatmapFileAttachment:
    """beatmap に紐づく取得済み osu file blob。"""

    beatmap_id: int
    blob_id: int
    checksum_md5: str
    source: str
    original_filename: str | None
    fetched_at: datetime
    verified_at: datetime | None
    id: int | None = None

    def __post_init__(self) -> None:
        _validate_md5(self.checksum_md5)
        if self.id is not None and self.id <= 0:
            msg = "id must be positive"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class Beatmap:
    """1 つの beatmap difficulty と取得状態。"""

    id: int
    beatmapset_id: int
    checksum_md5: str
    mode: str
    version: str
    total_length: int | None
    hit_length: int | None
    max_combo: int | None
    bpm: float | None
    cs: float | None
    od: float | None
    ar: float | None
    hp: float | None
    difficulty_rating: float | None
    official_status: BeatmapRankStatus
    official_status_source: BeatmapMetadataSource
    official_status_verified: BeatmapSourceVerification
    local_status_override: LocalBeatmapStatus | None
    metadata_fetch_state: BeatmapFetchState
    file_state: BeatmapFileState
    file_attachment: BeatmapFileAttachment | None
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None

    def __post_init__(self) -> None:
        _validate_md5(self.checksum_md5)
        _validate_local_override(self.local_status_override)

    @property
    def effective_status(self) -> BeatmapRankStatus:
        """ローカル上書きを反映した採用 status。"""

        if self.local_status_override is None:
            return self.official_status
        return BeatmapRankStatus(self.local_status_override.value)


@dataclass(slots=True, frozen=True)
class BeatmapSet:
    """同じ beatmapset に属する difficulty 群と set metadata。"""

    id: int
    artist: str
    title: str
    creator: str
    artist_unicode: str | None
    title_unicode: str | None
    official_status: BeatmapRankStatus
    official_status_source: BeatmapMetadataSource
    official_status_verified: BeatmapSourceVerification
    beatmaps: tuple[Beatmap, ...]
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None


def _validate_md5(checksum_md5: str) -> None:
    if not _MD5_PATTERN.fullmatch(checksum_md5):
        msg = "checksum_md5 must be a 32-character lowercase hexadecimal string"
        raise ValueError(msg)


def _validate_local_override(status: object) -> None:
    if status is None:
        return
    if status is BeatmapRankStatus.APPROVED:
        msg = "Approved cannot be used as a local override"
        raise ValueError(msg)
    if not isinstance(status, LocalBeatmapStatus):
        msg = "local_status_override must be a LocalBeatmapStatus or None"
        raise TypeError(msg)


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

_EXTERNAL_STATUS_MAP: dict[str, BeatmapRankStatus] = {
    "ranked": BeatmapRankStatus.RANKED,
    "approved": BeatmapRankStatus.APPROVED,
    "loved": BeatmapRankStatus.LOVED,
    "qualified": BeatmapRankStatus.QUALIFIED,
    "pending": BeatmapRankStatus.PENDING,
    "wip": BeatmapRankStatus.WIP,
    "graveyard": BeatmapRankStatus.GRAVEYARD,
}


def map_external_status(status: str) -> BeatmapRankStatus:
    """外部 provider の status 文字列を canonical status に変換する。"""

    normalized = status.strip().lower()
    return _EXTERNAL_STATUS_MAP.get(normalized, BeatmapRankStatus.UNKNOWN)


_STABLE_STATUSES: frozenset[BeatmapRankStatus] = frozenset(
    {BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED, BeatmapRankStatus.LOVED}
)
_PENDING_LIKE_STATUSES: frozenset[BeatmapRankStatus] = frozenset(
    {BeatmapRankStatus.QUALIFIED, BeatmapRankStatus.PENDING, BeatmapRankStatus.WIP}
)


def _is_mirror_sourced(beatmap: Beatmap) -> bool:
    return beatmap.official_status_source is BeatmapMetadataSource.MIRROR


@dataclass(slots=True, frozen=True)
class BeatmapFreshnessDecision:
    """metadata freshness policy の判定結果。"""

    is_stale: bool
    should_refresh: bool
    requests_official_refresh: bool
    next_refresh_at: datetime | None
    reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapFreshnessPolicy:
    """beatmap metadata を再取得すべきか判定する policy。"""

    ranked_refresh_interval: timedelta
    pending_refresh_interval: timedelta
    graveyard_refresh_interval: timedelta
    mirror_refresh_interval: timedelta

    def evaluate(
        self,
        beatmap: Beatmap,
        *,
        now: datetime,
        official_sources_available: bool = False,
        force_refresh: bool = False,
    ) -> BeatmapFreshnessDecision:
        """現在時刻と取得元から stale/refresh 判定を返す。"""

        next_refresh_at = self._effective_next_refresh_at(beatmap)
        is_stale = next_refresh_at is not None and next_refresh_at <= now

        if force_refresh:
            return BeatmapFreshnessDecision(
                is_stale=is_stale,
                should_refresh=True,
                requests_official_refresh=official_sources_available
                and _is_mirror_sourced(beatmap),
                next_refresh_at=next_refresh_at,
                reason="force_refresh",
            )

        if beatmap.metadata_fetch_state is BeatmapFetchState.PENDING_FETCH:
            return BeatmapFreshnessDecision(
                is_stale=is_stale,
                should_refresh=False,
                requests_official_refresh=False,
                next_refresh_at=next_refresh_at,
                reason="pending_fetch",
            )

        if beatmap.metadata_fetch_state is BeatmapFetchState.FAILED:
            return BeatmapFreshnessDecision(
                is_stale=is_stale,
                should_refresh=True,
                requests_official_refresh=official_sources_available
                and _is_mirror_sourced(beatmap),
                next_refresh_at=next_refresh_at,
                reason="failed_fetch",
            )

        if official_sources_available and _is_mirror_sourced(beatmap):
            return BeatmapFreshnessDecision(
                is_stale=True,
                should_refresh=True,
                requests_official_refresh=True,
                next_refresh_at=next_refresh_at,
                reason="mirror_official_refresh_due",
            )

        if is_stale:
            return BeatmapFreshnessDecision(
                is_stale=True,
                should_refresh=True,
                requests_official_refresh=official_sources_available
                and _is_mirror_sourced(beatmap),
                next_refresh_at=next_refresh_at,
                reason="stale",
            )

        return BeatmapFreshnessDecision(
            is_stale=False,
            should_refresh=False,
            requests_official_refresh=False,
            next_refresh_at=next_refresh_at,
            reason=None,
        )

    def _effective_next_refresh_at(self, beatmap: Beatmap) -> datetime | None:
        if beatmap.last_fetched_at is None:
            return beatmap.next_refresh_at
        if beatmap.next_refresh_at is None:
            return self._derive_next_refresh_at(beatmap)
        if beatmap.next_refresh_at <= beatmap.last_fetched_at:
            return self._derive_next_refresh_at(beatmap)
        return beatmap.next_refresh_at

    def _derive_next_refresh_at(self, beatmap: Beatmap) -> datetime | None:
        if beatmap.last_fetched_at is None:
            return None

        if _is_mirror_sourced(beatmap):
            return beatmap.last_fetched_at + self.mirror_refresh_interval

        status = beatmap.effective_status
        if status in _STABLE_STATUSES:
            return beatmap.last_fetched_at + self.ranked_refresh_interval
        if status in _PENDING_LIKE_STATUSES:
            return beatmap.last_fetched_at + self.pending_refresh_interval
        if status is BeatmapRankStatus.GRAVEYARD:
            return beatmap.last_fetched_at + self.graveyard_refresh_interval
        return beatmap.last_fetched_at + self.pending_refresh_interval


@dataclass(slots=True, frozen=True)
class BeatmapEligibility:
    """score submission と leaderboard 更新で使う beatmap 適格性。"""

    accepts_scores: bool
    has_leaderboard: bool
    awards_ranked_pp: bool
    awards_loved_pp: bool
    requires_osu_file_for_pp: bool
    is_officially_verified: bool
    is_mirror_derived: bool
    accepts_failed_scores: bool
    failed_scores_have_leaderboard: bool
    failed_scores_update_best_score: bool
    failed_scores_award_ranked_pp: bool
    failed_scores_award_loved_pp: bool
    denial_reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapResolveOptions:
    """beatmap resolution の挙動を制御する option。"""

    require_osu_file: bool = False
    wait_timeout_seconds: float = 0.0
    force_refresh: bool = False


@dataclass(slots=True, frozen=True)
class BeatmapResolveResult:
    """単一 beatmap resolution の構造化された結果。"""

    beatmap: Beatmap | None
    beatmapset: BeatmapSet | None
    eligibility: BeatmapEligibility | None
    metadata_status: BeatmapFetchState
    file_status: BeatmapFileState
    source: BeatmapMetadataSource | None
    verified: bool
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None
    reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapSetResolveResult:
    """beatmapset resolution の構造化された結果。"""

    beatmapset: BeatmapSet | None
    metadata_status: BeatmapFetchState
    source: BeatmapMetadataSource | None
    verified: bool
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None
    reason: str | None


class BeatmapFetchTargetKind(Enum):
    """beatmap fetch target encoding owned by the beatmap domain."""

    METADATA_BY_BEATMAP_ID = "metadata:beatmap"
    METADATA_BY_BEATMAPSET_ID = "metadata:beatmapset"
    METADATA_BY_CHECKSUM = "metadata:checksum"
    FILE_BY_BEATMAP_ID = "file:beatmap"


class BeatmapMetadataLookupKind(Enum):
    """metadata provider lookup shape derived from a fetch target."""

    BEATMAP_ID = "beatmap_id"
    BEATMAPSET_ID = "beatmapset_id"
    CHECKSUM = "checksum"


@dataclass(slots=True, frozen=True)
class BeatmapMetadataLookupTarget:
    """Provider-neutral metadata lookup requested by a fetch target."""

    kind: BeatmapMetadataLookupKind
    value: str

    def int_value(self) -> int:
        """Return the lookup value as a positive integer identifier."""
        value = int(self.value)
        if value <= 0:
            msg = f"lookup value must be positive: {self.value}"
            raise ValueError(msg)
        return value


@dataclass(slots=True, frozen=True)
class BeatmapFetchQueuePayload:
    """worker queue に渡す primitive payload。"""

    target_type: str
    target_key: str
    force_refresh: bool = False


@dataclass(slots=True, frozen=True)
class BeatmapFetchTarget:
    """fetch queue encoding を隠す beatmap metadata/file 取得対象。"""

    target_type: str
    target_key: str
    force_refresh: bool = field(default=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not self.target_type:
            raise ValueError("target_type must not be empty")
        if not self.target_key:
            raise ValueError("target_key must not be empty")

    @property
    def kind(self) -> BeatmapFetchTargetKind:
        """Return the typed fetch target kind."""
        try:
            return BeatmapFetchTargetKind(self.target_type)
        except ValueError as exc:
            msg = f"unsupported beatmap fetch target type: {self.target_type}"
            raise ValueError(msg) from exc

    @property
    def is_file_fetch(self) -> bool:
        """Return whether this target is handled by the file fetch worker."""
        return self.kind is BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID

    def metadata_lookup_target(self) -> BeatmapMetadataLookupTarget:
        """Return the metadata lookup represented by this fetch target."""
        match self.kind:
            case BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID:
                return BeatmapMetadataLookupTarget(
                    kind=BeatmapMetadataLookupKind.BEATMAP_ID,
                    value=self.target_key,
                )
            case BeatmapFetchTargetKind.METADATA_BY_BEATMAPSET_ID:
                return BeatmapMetadataLookupTarget(
                    kind=BeatmapMetadataLookupKind.BEATMAPSET_ID,
                    value=self.target_key,
                )
            case BeatmapFetchTargetKind.METADATA_BY_CHECKSUM:
                return BeatmapMetadataLookupTarget(
                    kind=BeatmapMetadataLookupKind.CHECKSUM,
                    value=self.target_key,
                )
            case BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID:
                msg = "file fetch target cannot be used for metadata lookup"
                raise ValueError(msg)

    def file_beatmap_id(self) -> int:
        """Return the beatmap id represented by a file fetch target."""
        if self.kind is not BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID:
            msg = f"unsupported file fetch target type: {self.target_type}"
            raise ValueError(msg)
        return int(self.target_key)

    def queue_payload(self) -> BeatmapFetchQueuePayload:
        """encoding の詳細を隠して worker queue payload を返す。"""
        return BeatmapFetchQueuePayload(
            target_type=self.target_type,
            target_key=self.target_key,
            force_refresh=self.force_refresh,
        )

    @classmethod
    def from_queue_payload(
        cls,
        *,
        target_type: str,
        target_key: str,
        force_refresh: bool = False,
    ) -> BeatmapFetchTarget:
        """worker queue payload から fetch target を復元する。"""
        return cls(
            target_type=target_type,
            target_key=target_key,
            force_refresh=force_refresh,
        )

    @classmethod
    def metadata_by_beatmap_id(
        cls, beatmap_id: int, *, force_refresh: bool = False
    ) -> BeatmapFetchTarget:
        """beatmap id を指定した metadata fetch target を作る。"""
        return cls(
            target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID.value,
            target_key=str(beatmap_id),
            force_refresh=force_refresh,
        )

    @classmethod
    def metadata_by_beatmapset_id(
        cls, beatmapset_id: int, *, force_refresh: bool = False
    ) -> BeatmapFetchTarget:
        """beatmapset id を指定した metadata fetch target を作る。"""
        return cls(
            target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAPSET_ID.value,
            target_key=str(beatmapset_id),
            force_refresh=force_refresh,
        )

    @classmethod
    def metadata_by_checksum(
        cls, checksum_md5: str, *, force_refresh: bool = False
    ) -> BeatmapFetchTarget:
        """MD5 checksum を指定した metadata fetch target を作る。"""
        return cls(
            target_type=BeatmapFetchTargetKind.METADATA_BY_CHECKSUM.value,
            target_key=checksum_md5,
            force_refresh=force_refresh,
        )

    @classmethod
    def file_by_beatmap_id(cls, beatmap_id: int) -> BeatmapFetchTarget:
        return cls(
            target_type=BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID.value,
            target_key=str(beatmap_id),
        )


@dataclass(slots=True, frozen=True)
class BeatmapFetchRecord:
    """fetch queue 上の取得試行状態。"""

    target: BeatmapFetchTarget
    status: BeatmapFetchState
    attempt_count: int
    last_error: str | None
    pending_since: datetime | None
    last_attempted_at: datetime | None


# ---------------------------------------------------------------------------
# Provider contracts -- snapshot types and metadata provider Protocol
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class BeatmapSnapshot:
    """provider から取り込んだ単一 beatmap の snapshot。"""

    beatmap_id: int
    beatmapset_id: int
    checksum_md5: str
    mode: str
    version: str
    official_status: BeatmapRankStatus
    official_status_source: BeatmapMetadataSource
    official_status_verified: BeatmapSourceVerification
    local_status_override: LocalBeatmapStatus | None = None
    total_length: int | None = None
    hit_length: int | None = None
    max_combo: int | None = None
    bpm: float | None = None
    cs: float | None = None
    od: float | None = None
    ar: float | None = None
    hp: float | None = None
    difficulty_rating: float | None = None
    last_fetched_at: datetime | None = None
    next_refresh_at: datetime | None = None

    def __post_init__(self) -> None:
        _validate_md5(self.checksum_md5)


@dataclass(slots=True, frozen=True)
class BeatmapsetSnapshot:
    """provider から取り込んだ beatmapset 全体の snapshot。"""

    beatmapset_id: int
    artist: str
    title: str
    creator: str
    source: BeatmapMetadataSource
    verified: BeatmapSourceVerification
    official_status: BeatmapRankStatus
    official_status_source: BeatmapMetadataSource
    official_status_verified: BeatmapSourceVerification
    beatmaps: tuple[BeatmapSnapshot, ...]
    artist_unicode: str | None = None
    title_unicode: str | None = None
    last_fetched_at: datetime | None = None
    next_refresh_at: datetime | None = None


@runtime_checkable
class BeatmapMetadataProvider(Protocol):
    """beatmap metadata provider の seam。"""

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None: ...
    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None: ...
    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None: ...


class BeatmapFileSource(Enum):
    """osu file を取得した source。"""

    OSU_CURRENT = "osu_current"
    OSU_LEGACY = "osu_legacy"
    COMMUNITY_MIRROR = "community_mirror"
    ARCHIVE_EXTRACTED = "archive_extracted"


@dataclass(slots=True, frozen=True)
class OsuFileFetchResult:
    """osu file provider が返す取得済み file。"""

    beatmap_id: int
    body: bytes
    source: BeatmapFileSource
    original_filename: str | None


@runtime_checkable
class BeatmapFileProvider(Protocol):
    """osu file provider の seam。"""

    async def fetch_osu_file(self, beatmap_id: int) -> OsuFileFetchResult: ...
