from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

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
