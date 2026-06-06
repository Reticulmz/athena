"""Beatmap source contracts and provider-neutral infrastructure DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime


class BeatmapMetadataSourceName(Enum):
    """Provider-side metadata source names."""

    OFFICIAL = "official"
    LEGACY_OFFICIAL = "legacy_official"
    MIRROR = "mirror"


@dataclass(slots=True, frozen=True)
class ProviderBeatmapSnapshot:
    beatmap_id: int
    beatmapset_id: int
    checksum_md5: str
    mode: str
    version: str
    official_status: str
    official_status_source: BeatmapMetadataSourceName
    official_status_verified: bool
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


@dataclass(slots=True, frozen=True)
class ProviderBeatmapsetSnapshot:
    beatmapset_id: int
    artist: str
    title: str
    creator: str
    source: BeatmapMetadataSourceName
    verified: bool
    official_status: str
    official_status_source: BeatmapMetadataSourceName
    official_status_verified: bool
    beatmaps: tuple[ProviderBeatmapSnapshot, ...]
    artist_unicode: str | None = None
    title_unicode: str | None = None
    last_fetched_at: datetime | None = None
    next_refresh_at: datetime | None = None


@runtime_checkable
class ProviderBeatmapMetadataProvider(Protocol):
    async def lookup_by_beatmap_id(self, beatmap_id: int) -> ProviderBeatmapsetSnapshot | None: ...

    async def lookup_by_beatmapset_id(
        self, beatmapset_id: int
    ) -> ProviderBeatmapsetSnapshot | None: ...

    async def lookup_by_checksum(self, checksum_md5: str) -> ProviderBeatmapsetSnapshot | None: ...


class BeatmapFileSource(Enum):
    """Identifies which source served a fetched .osu file."""

    OSU_CURRENT = "osu_current"
    OSU_LEGACY = "osu_legacy"
    COMMUNITY_MIRROR = "community_mirror"
    ARCHIVE_EXTRACTED = "archive_extracted"


@dataclass(slots=True, frozen=True)
class OsuFileFetchResult:
    """Bytes fetched from a .osu file source, with provenance metadata."""

    beatmap_id: int
    body: bytes
    source: BeatmapFileSource
    original_filename: str | None


@runtime_checkable
class BeatmapFileProvider(Protocol):
    async def fetch_osu_file(self, beatmap_id: int) -> OsuFileFetchResult: ...
