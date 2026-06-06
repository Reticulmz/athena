"""Map osu! API v2 JSON responses to provider-neutral snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict, cast

from osu_server.infrastructure.beatmaps.contracts import (
    BeatmapMetadataSourceName,
    ProviderBeatmapsetSnapshot,
    ProviderBeatmapSnapshot,
)

_SOURCE = BeatmapMetadataSourceName.OFFICIAL
_VERIFIED = True


class _BeatmapJSON(TypedDict, total=False):
    """Subset of osu! API v2 beatmap JSON fields consumed by the mapper."""

    id: int
    beatmapset_id: int
    checksum: str
    mode: str
    version: str
    status: str
    total_length: int | None
    hit_length: int | None
    max_combo: int | None
    bpm: float | None
    cs: float | None
    accuracy: float | None
    ar: float | None
    drain: float | None
    difficulty_rating: float | None
    beatmapset: _BeatmapsetJSON


class _BeatmapsetJSON(TypedDict, total=False):
    """Subset of osu! API v2 beatmapset JSON fields consumed by the mapper."""

    id: int
    artist: str
    title: str
    creator: str
    artist_unicode: str | None
    title_unicode: str | None
    status: str
    beatmaps: list[_BeatmapJSON]


def beatmap_json_to_snapshot(
    data: dict[str, object], *, now: datetime | None = None
) -> ProviderBeatmapsetSnapshot:
    """Convert osu! API v2 beatmap or beatmapset JSON to a snapshot."""
    _now = now or datetime.now(UTC)
    if "beatmaps" in data:
        return _from_beatmapset_json(cast("_BeatmapsetJSON", cast("object", data)), now=_now)
    return _from_beatmap_json(cast("_BeatmapJSON", cast("object", data)), now=_now)


def _from_beatmap_json(data: _BeatmapJSON, *, now: datetime) -> ProviderBeatmapsetSnapshot:
    beatmapset_data = data.get("beatmapset") or {}
    return _from_beatmapset_json(
        {
            "id": beatmapset_data.get("id", 0),
            "artist": beatmapset_data.get("artist", ""),
            "title": beatmapset_data.get("title", ""),
            "creator": beatmapset_data.get("creator", ""),
            "artist_unicode": beatmapset_data.get("artist_unicode"),
            "title_unicode": beatmapset_data.get("title_unicode"),
            "status": beatmapset_data.get("status", ""),
            "beatmaps": [data],
        },
        now=now,
    )


def _from_beatmapset_json(data: _BeatmapsetJSON, *, now: datetime) -> ProviderBeatmapsetSnapshot:
    beatmapset_id = data.get("id", 0)
    beatmapset_status = _map_status(data.get("status", ""))

    beatmaps_raw: list[_BeatmapJSON] = data.get("beatmaps") or []
    child_snapshots = tuple(
        ProviderBeatmapSnapshot(
            beatmap_id=bm.get("id", 0),
            beatmapset_id=bm.get("beatmapset_id", beatmapset_id),
            checksum_md5=bm.get("checksum", "0" * 32),
            mode=bm.get("mode", ""),
            version=bm.get("version", ""),
            official_status=_map_status(bm.get("status", "")),
            official_status_source=_SOURCE,
            official_status_verified=_VERIFIED,
            total_length=bm.get("total_length"),
            hit_length=bm.get("hit_length"),
            max_combo=bm.get("max_combo"),
            bpm=_maybe_float(bm.get("bpm")),
            cs=_maybe_float(bm.get("cs")),
            od=_maybe_float(bm.get("accuracy")),
            ar=_maybe_float(bm.get("ar")),
            hp=_maybe_float(bm.get("drain")),
            difficulty_rating=_maybe_float(bm.get("difficulty_rating")),
            last_fetched_at=now,
            next_refresh_at=now,
        )
        for bm in beatmaps_raw
    )

    _ = now
    return ProviderBeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist=data.get("artist", ""),
        title=data.get("title", ""),
        creator=data.get("creator", ""),
        source=_SOURCE,
        verified=_VERIFIED,
        official_status=beatmapset_status,
        official_status_source=_SOURCE,
        official_status_verified=_VERIFIED,
        beatmaps=child_snapshots,
        artist_unicode=data.get("artist_unicode"),
        title_unicode=data.get("title_unicode"),
        last_fetched_at=now,
        next_refresh_at=now,
    )


def _map_status(raw: str) -> str:
    return raw.strip().lower()


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # pyright: ignore[reportArgumentType]
    except (TypeError, ValueError):
        return None
