"""Beatmap file source contracts -- types and Protocol for .osu file providers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


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
