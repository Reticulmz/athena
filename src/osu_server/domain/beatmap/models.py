from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime, timedelta

_MD5_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class BeatmapRankStatus(Enum):
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
    RANKED = "ranked"
    LOVED = "loved"
    QUALIFIED = "qualified"
    PENDING = "pending"
    WIP = "wip"
    GRAVEYARD = "graveyard"
    NOT_SUBMITTED = "not_submitted"
    UNKNOWN = "unknown"


class BeatmapMetadataSource(Enum):
    OFFICIAL = "official"
    LEGACY_OFFICIAL = "legacy_official"
    MIRROR = "mirror"


class BeatmapSourceVerification(Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class BeatmapFetchState(Enum):
    FRESH = "fresh"
    STALE = "stale"
    PENDING_FETCH = "pending_fetch"
    FAILED = "failed"


class BeatmapFileState(Enum):
    AVAILABLE = "available"
    PENDING_FETCH = "pending_fetch"
    MISSING = "missing"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class BeatmapFileAttachment:
    beatmap_id: int
    blob_id: int
    checksum_md5: str
    source: str
    original_filename: str | None
    fetched_at: datetime
    verified_at: datetime | None

    def __post_init__(self) -> None:
        _validate_md5(self.checksum_md5)


@dataclass(slots=True, frozen=True)
class Beatmap:
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
        if self.local_status_override is None:
            return self.official_status
        return BeatmapRankStatus(self.local_status_override.value)


@dataclass(slots=True, frozen=True)
class BeatmapSet:
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
    is_stale: bool
    should_refresh: bool
    requests_official_refresh: bool
    next_refresh_at: datetime | None
    reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapFreshnessPolicy:
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
        next_refresh_at = beatmap.next_refresh_at or self._derive_next_refresh_at(beatmap)
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

    def _derive_next_refresh_at(self, beatmap: Beatmap) -> datetime | None:
        if beatmap.last_fetched_at is None:
            return None

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
    """Options controlling beatmap resolution behavior."""

    require_osu_file: bool = False
    wait_timeout_seconds: float = 0.0
    force_refresh: bool = False


@dataclass(slots=True, frozen=True)
class BeatmapResolveResult:
    """Structured result of a beatmap resolution for a single beatmap."""

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
    """Structured result of a beatmapset resolution."""

    beatmapset: BeatmapSet | None
    metadata_status: BeatmapFetchState
    source: BeatmapMetadataSource | None
    verified: bool
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None
    reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapFetchTarget:
    target_type: str
    target_key: str

    def __post_init__(self) -> None:
        if not self.target_type:
            raise ValueError("target_type must not be empty")
        if not self.target_key:
            raise ValueError("target_key must not be empty")

    @classmethod
    def metadata_by_beatmap_id(cls, beatmap_id: int) -> BeatmapFetchTarget:
        return cls(target_type="metadata:beatmap", target_key=str(beatmap_id))

    @classmethod
    def metadata_by_beatmapset_id(cls, beatmapset_id: int) -> BeatmapFetchTarget:
        return cls(target_type="metadata:beatmapset", target_key=str(beatmapset_id))

    @classmethod
    def metadata_by_checksum(cls, checksum_md5: str) -> BeatmapFetchTarget:
        return cls(target_type="metadata:checksum", target_key=checksum_md5)

    @classmethod
    def file_by_beatmap_id(cls, beatmap_id: int) -> BeatmapFetchTarget:
        return cls(target_type="file:beatmap", target_key=str(beatmap_id))


@dataclass(slots=True, frozen=True)
class BeatmapFetchRecord:
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
    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None: ...
    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None: ...
    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None: ...


class BeatmapFileSource(Enum):
    OSU_CURRENT = "osu_current"
    OSU_LEGACY = "osu_legacy"
    COMMUNITY_MIRROR = "community_mirror"
    ARCHIVE_EXTRACTED = "archive_extracted"


@dataclass(slots=True, frozen=True)
class OsuFileFetchResult:
    beatmap_id: int
    body: bytes
    source: BeatmapFileSource
    original_filename: str | None


@runtime_checkable
class BeatmapFileProvider(Protocol):
    async def fetch_osu_file(self, beatmap_id: int) -> OsuFileFetchResult: ...
