"""Map osu! API v2 JSON responses to provider-neutral snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
    map_external_status,
)


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
    last_update: str | None
    last_updated: str | None
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
    last_updated: str | None
    beatmaps: list[_BeatmapJSON]


def beatmap_json_to_snapshot(
    data: dict[str, object],
    *,
    now: datetime | None = None,
    source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    verification: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
) -> BeatmapsetSnapshot:
    """Convert osu! API v2 beatmap or beatmapset JSON to a snapshot."""
    _now = now or datetime.now(UTC)
    if "beatmaps" in data:
        return _from_beatmapset_json(
            cast("_BeatmapsetJSON", cast("object", data)),
            now=_now,
            source=source,
            verification=verification,
        )
    return _from_beatmap_json(
        cast("_BeatmapJSON", cast("object", data)),
        now=_now,
        source=source,
        verification=verification,
    )


def beatmap_v1_json_to_snapshot(
    items: Sequence[Mapping[str, object]],
    *,
    now: datetime | None = None,
    source: BeatmapMetadataSource = BeatmapMetadataSource.MIRROR,
    verification: BeatmapSourceVerification = BeatmapSourceVerification.UNVERIFIED,
) -> BeatmapsetSnapshot | None:
    """Convert osu! API v1 flat beatmap rows to a snapshot."""
    if not items:
        return None

    _now = now or datetime.now(UTC)
    first = items[0]
    beatmapset_id = _maybe_int(first.get("beatmapset_id")) or 0
    beatmaps = tuple(
        BeatmapSnapshot(
            beatmap_id=_maybe_int(item.get("beatmap_id")) or 0,
            beatmapset_id=_maybe_int(item.get("beatmapset_id")) or beatmapset_id,
            checksum_md5=_maybe_str(item.get("file_md5")) or "0" * 32,
            mode=_mode_text(item.get("mode")),
            version=_maybe_str(item.get("version")) or "",
            official_status=map_external_status(_status_text(item.get("approved"))),
            official_status_source=source,
            official_status_verified=verification,
            total_length=_maybe_int(item.get("total_length")),
            hit_length=_maybe_int(item.get("hit_length")),
            max_combo=_maybe_int(item.get("max_combo")),
            bpm=_maybe_float(item.get("bpm")),
            cs=_maybe_float(item.get("diff_size")),
            od=_maybe_float(item.get("diff_overall")),
            ar=_maybe_float(item.get("diff_approach")),
            hp=_maybe_float(item.get("diff_drain")),
            difficulty_rating=_maybe_float(item.get("difficultyrating")),
            last_fetched_at=_now,
            next_refresh_at=_now,
            official_last_updated_at=_maybe_datetime(item.get("last_update")),
        )
        for item in items
    )

    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist=_maybe_str(first.get("artist")) or "",
        title=_maybe_str(first.get("title")) or "",
        creator=_maybe_str(first.get("creator")) or "",
        source=source,
        verified=verification,
        official_status=map_external_status(_status_text(first.get("approved"))),
        official_status_source=source,
        official_status_verified=verification,
        beatmaps=beatmaps,
        artist_unicode=_maybe_str(first.get("artist_unicode")),
        title_unicode=_maybe_str(first.get("title_unicode")),
        last_fetched_at=_now,
        next_refresh_at=_now,
    )


def _from_beatmap_json(
    data: _BeatmapJSON,
    *,
    now: datetime,
    source: BeatmapMetadataSource,
    verification: BeatmapSourceVerification,
) -> BeatmapsetSnapshot:
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
        source=source,
        verification=verification,
    )


def _from_beatmapset_json(
    data: _BeatmapsetJSON,
    *,
    now: datetime,
    source: BeatmapMetadataSource,
    verification: BeatmapSourceVerification,
) -> BeatmapsetSnapshot:
    beatmapset_id = data.get("id", 0)
    beatmapset_status = data.get("status", "")
    beatmapset_last_updated_at = _maybe_datetime(data.get("last_updated"))

    beatmaps_raw: list[_BeatmapJSON] = data.get("beatmaps") or []
    child_snapshots = tuple(
        BeatmapSnapshot(
            beatmap_id=bm.get("id", 0),
            beatmapset_id=bm.get("beatmapset_id", beatmapset_id),
            checksum_md5=bm.get("checksum", "0" * 32),
            mode=bm.get("mode", ""),
            version=bm.get("version", ""),
            official_status=map_external_status(bm.get("status", "")),
            official_status_source=source,
            official_status_verified=verification,
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
            official_last_updated_at=(
                _maybe_datetime(bm.get("last_updated"))
                or _maybe_datetime(bm.get("last_update"))
                or beatmapset_last_updated_at
            ),
        )
        for bm in beatmaps_raw
    )

    _ = now
    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist=data.get("artist", ""),
        title=data.get("title", ""),
        creator=data.get("creator", ""),
        source=source,
        verified=verification,
        official_status=map_external_status(beatmapset_status),
        official_status_source=source,
        official_status_verified=verification,
        beatmaps=child_snapshots,
        artist_unicode=data.get("artist_unicode"),
        title_unicode=data.get("title_unicode"),
        last_fetched_at=now,
        next_refresh_at=now,
    )


def _maybe_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _maybe_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return str(value)
    return None


def _maybe_datetime(value: object) -> datetime | None:
    text = _maybe_str(value)
    if text is None:
        return None
    normalized = text.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _mode_text(value: object) -> str:
    mode = _maybe_int(value)
    if mode is not None:
        return {
            0: BeatmapMode.OSU.value,
            1: BeatmapMode.TAIKO.value,
            2: BeatmapMode.FRUITS.value,
            3: BeatmapMode.MANIA.value,
        }.get(mode, BeatmapMode.UNKNOWN.value)
    text = (_maybe_str(value) or "").strip()
    try:
        return BeatmapMode(text).value
    except ValueError:
        return BeatmapMode.UNKNOWN.value


def _status_text(value: object) -> str:
    approved = _maybe_int(value)
    if approved is not None:
        return {
            -2: "graveyard",
            -1: "wip",
            0: "pending",
            1: "ranked",
            2: "approved",
            3: "qualified",
            4: "loved",
        }.get(approved, "")
    return (_maybe_str(value) or "").strip()


def _maybe_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
