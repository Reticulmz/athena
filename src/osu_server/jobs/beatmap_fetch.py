"""Idempotent background beatmap metadata fetch job.

``FetchBeatmapMetadataJob`` fetches beatmapset metadata through a
``BeatmapMetadataProvider`` (typically the composite official+mirror
provider), converts the snapshot to a domain ``BeatmapSet``, and persists
it through a ``BeatmapRepository``.

The job is idempotent: it uses ``try_mark_fetch_pending`` as a
concurrency-safe gate so that only one fetch proceeds for the same
target.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from osu_server.domain.beatmap import (
        BeatmapMetadataProvider,
        BeatmapSet,
        BeatmapsetSnapshot,
    )
    from osu_server.repositories.interfaces.beatmap_repository import (
        BeatmapFetchTarget,
        BeatmapRepository,
    )

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class FetchBeatmapMetadataJob:
    """Fetch beatmapset metadata idempotently from a composite provider.

    The job marks the target as pending, fetches metadata (official first,
    mirror fallback), converts the snapshot to domain objects, and persists
    everything through the repository. If the target is already pending
    the job is a no-op.
    """

    def __init__(
        self,
        *,
        repository: BeatmapRepository,
        metadata_provider: BeatmapMetadataProvider,
    ) -> None:
        self._repo: BeatmapRepository = repository
        self._provider: BeatmapMetadataProvider = metadata_provider

    async def execute(self, target: BeatmapFetchTarget) -> None:
        """Run the idempotent fetch cycle for *target*."""
        now = datetime.now(UTC)

        acquired = await self._repo.try_mark_fetch_pending(target, now)
        if not acquired:
            logger.debug(
                "beatmap_fetch_already_pending",
                target_type=target.target_type,
                target_key=target.target_key,
            )
            return

        snapshot = await self._lookup(target)

        if snapshot is None:
            await self._repo.mark_fetch_failed(
                target,
                "all configured metadata providers returned no result",
                now,
            )
            return

        beatmapset = _snapshot_to_beatmapset(snapshot)
        await self._repo.save_beatmapset_snapshot(beatmapset)
        await self._repo.mark_fetch_succeeded(target, now)

    async def _lookup(self, target: BeatmapFetchTarget) -> BeatmapsetSnapshot | None:
        target_type = target.target_type
        if target_type == "metadata:beatmap":
            return await self._provider.lookup_by_beatmap_id(int(target.target_key))
        if target_type == "metadata:beatmapset":
            return await self._provider.lookup_by_beatmapset_id(int(target.target_key))
        if target_type == "metadata:checksum":
            return await self._provider.lookup_by_checksum(target.target_key)
        raise ValueError(f"unsupported metadata fetch target type: {target_type}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _snapshot_to_beatmapset(snapshot: BeatmapsetSnapshot) -> BeatmapSet:
    """Convert a provider snapshot to a domain ``BeatmapSet``."""
    from osu_server.domain.beatmap import (  # noqa: PLC0415
        Beatmap,
        BeatmapFetchState,
        BeatmapFileState,
        BeatmapSet,
    )

    beatmaps = tuple(
        Beatmap(
            id=bm.beatmap_id,
            beatmapset_id=bm.beatmapset_id,
            checksum_md5=bm.checksum_md5,
            mode=bm.mode,
            version=bm.version,
            total_length=bm.total_length,
            hit_length=bm.hit_length,
            max_combo=bm.max_combo,
            bpm=bm.bpm,
            cs=bm.cs,
            od=bm.od,
            ar=bm.ar,
            hp=bm.hp,
            difficulty_rating=bm.difficulty_rating,
            official_status=bm.official_status,
            official_status_source=bm.official_status_source,
            official_status_verified=bm.official_status_verified,
            local_status_override=bm.local_status_override,
            metadata_fetch_state=BeatmapFetchState.FRESH,
            file_state=BeatmapFileState.MISSING,
            file_attachment=None,
            last_fetched_at=bm.last_fetched_at,
            next_refresh_at=bm.next_refresh_at,
        )
        for bm in snapshot.beatmaps
    )

    return BeatmapSet(
        id=snapshot.beatmapset_id,
        artist=snapshot.artist,
        title=snapshot.title,
        creator=snapshot.creator,
        artist_unicode=snapshot.artist_unicode,
        title_unicode=snapshot.title_unicode,
        official_status=snapshot.official_status,
        official_status_source=snapshot.official_status_source,
        official_status_verified=snapshot.official_status_verified,
        beatmaps=beatmaps,
        last_fetched_at=snapshot.last_fetched_at,
        next_refresh_at=snapshot.next_refresh_at,
    )


__all__ = ["FetchBeatmapMetadataJob"]
