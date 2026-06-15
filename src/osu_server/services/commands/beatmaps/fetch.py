"""Beatmap fetch command use-cases."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

import structlog

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileAttachment,
    BeatmapFileState,
    BeatmapSet,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        BeatmapFileProvider,
        BeatmapMetadataProvider,
        BeatmapsetSnapshot,
    )
    from osu_server.domain.storage.blobs import BlobStoreResult
    from osu_server.repositories.interfaces.commands.beatmaps import BeatmapCommandRepository

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]

_OSU_BEATMAP_CONTENT_TYPE = "application/x-osu-beatmap"


class BeatmapBlobStorage(Protocol):
    async def put_bytes(
        self,
        data: bytes,
        *,
        content_type: str,
    ) -> BlobStoreResult: ...


class FetchBeatmapMetadataUseCase:
    """Fetch beatmap metadata idempotently from a metadata provider."""

    def __init__(
        self,
        *,
        repository: BeatmapCommandRepository,
        metadata_provider: BeatmapMetadataProvider,
    ) -> None:
        self._repo: BeatmapCommandRepository = repository
        self._provider: BeatmapMetadataProvider = metadata_provider

    async def execute(self, target: BeatmapFetchTarget) -> None:
        """Run the idempotent metadata fetch cycle for *target*."""
        now = datetime.now(UTC)

        acquired = await self._repo.try_mark_fetch_pending(target, now)
        if not acquired:
            logger.debug(
                "beatmap_fetch_already_pending",
                target_type=target.target_type,
                target_key=target.target_key,
            )
            return

        logger.info(
            "beatmap_metadata_fetch_started",
            target_type=target.target_type,
            target_key=target.target_key,
        )

        snapshot = await self._lookup(target)

        if snapshot is None:
            await self._repo.mark_fetch_failed(
                target,
                "all configured metadata providers returned no result",
                now,
            )
            logger.error(
                "beatmap_metadata_fetch_failed",
                target_type=target.target_type,
                target_key=target.target_key,
                error="all configured metadata providers returned no result",
            )
            return

        beatmapset = _snapshot_to_beatmapset(snapshot)
        await self._repo.save_beatmapset_snapshot(beatmapset)
        await self._repo.mark_fetch_succeeded(target, now)

        logger.info(
            "beatmap_metadata_fetch_succeeded",
            target_type=target.target_type,
            target_key=target.target_key,
            beatmapset_id=snapshot.beatmapset_id,
            source=snapshot.official_status_source.value,
            verified=(snapshot.official_status_verified.value == "verified"),
        )

    async def _lookup(self, target: BeatmapFetchTarget) -> BeatmapsetSnapshot | None:
        target_type = target.target_type
        if target_type == "metadata:beatmap":
            return await self._provider.lookup_by_beatmap_id(int(target.target_key))
        if target_type == "metadata:beatmapset":
            return await self._provider.lookup_by_beatmapset_id(int(target.target_key))
        if target_type == "metadata:checksum":
            return await self._provider.lookup_by_checksum(target.target_key)
        raise ValueError(f"unsupported metadata fetch target type: {target_type}")


class FetchBeatmapFileUseCase:
    """Fetch and verify a .osu file idempotently, then attach it as a blob."""

    def __init__(
        self,
        *,
        repository: BeatmapCommandRepository,
        file_provider: BeatmapFileProvider,
        blob_storage: BeatmapBlobStorage,
    ) -> None:
        self._repo: BeatmapCommandRepository = repository
        self._provider: BeatmapFileProvider = file_provider
        self._blob: BeatmapBlobStorage = blob_storage

    async def execute(self, target: BeatmapFetchTarget) -> None:
        """Run the idempotent file fetch cycle for *target*."""
        now = datetime.now(UTC)

        acquired = await self._repo.try_mark_fetch_pending(target, now)
        if not acquired:
            logger.debug(
                "beatmap_file_fetch_already_pending",
                target_type=target.target_type,
                target_key=target.target_key,
            )
            return

        logger.info(
            "beatmap_file_fetch_started",
            target_type=target.target_type,
            target_key=target.target_key,
        )

        if target.target_type != "file:beatmap":
            await self._repo.mark_fetch_failed(
                target,
                f"unsupported file fetch target type: {target.target_type}",
                now,
            )
            logger.error(
                "beatmap_file_fetch_failed",
                target_type=target.target_type,
                target_key=target.target_key,
                error=f"unsupported file fetch target type: {target.target_type}",
            )
            return

        beatmap_id = int(target.target_key)

        beatmap = await self._repo.get_beatmap(beatmap_id)
        if beatmap is None:
            await self._repo.mark_fetch_failed(
                target,
                f"beatmap {beatmap_id} not found in repository",
                now,
            )
            logger.error(
                "beatmap_file_fetch_failed",
                target_type=target.target_type,
                target_key=target.target_key,
                beatmap_id=beatmap_id,
                error=f"beatmap {beatmap_id} not found in repository",
            )
            return

        expected_md5 = beatmap.checksum_md5
        existing_attachment = await self._repo.get_current_file_attachment(beatmap_id)
        if existing_attachment is not None and existing_attachment.checksum_md5 == expected_md5:
            await self._repo.mark_fetch_succeeded(target, now)
            logger.info(
                "beatmap_file_fetch_succeeded",
                target_type=target.target_type,
                target_key=target.target_key,
                beatmap_id=beatmap_id,
                source=existing_attachment.source,
            )
            return

        try:
            result = await self._provider.fetch_osu_file(beatmap_id)
        except Exception as exc:
            await self._repo.mark_fetch_failed(
                target,
                f"{type(exc).__name__}: {exc}",
                now,
            )
            logger.error(
                "beatmap_file_fetch_failed",
                target_type=target.target_type,
                target_key=target.target_key,
                beatmap_id=beatmap_id,
                error=f"{type(exc).__name__}: {exc}",
                exc_info=True,
            )
            return

        fetched_md5 = hashlib.md5(result.body, usedforsecurity=False).hexdigest()

        if fetched_md5 != expected_md5:
            await self._repo.mark_fetch_failed(
                target,
                f"checksum mismatch: expected {expected_md5}, got {fetched_md5}",
                now,
            )
            logger.error(
                "beatmap_file_checksum_mismatch",
                beatmap_id=beatmap_id,
                expected_md5_prefix=expected_md5[:8],
                fetched_md5_prefix=fetched_md5[:8],
            )
            logger.error(
                "beatmap_file_fetch_failed",
                target_type=target.target_type,
                target_key=target.target_key,
                beatmap_id=beatmap_id,
                error="checksum mismatch",
            )
            return

        store_result = await self._blob.put_bytes(
            result.body,
            content_type=_OSU_BEATMAP_CONTENT_TYPE,
        )
        attachment = BeatmapFileAttachment(
            beatmap_id=beatmap_id,
            blob_id=store_result.blob.id,
            checksum_md5=expected_md5,
            source=result.source.value,
            original_filename=result.original_filename,
            fetched_at=now,
            verified_at=now,
        )
        _ = await self._repo.attach_osu_file(attachment)
        await self._repo.mark_fetch_succeeded(target, now)

        logger.info(
            "beatmap_file_fetch_succeeded",
            target_type=target.target_type,
            target_key=target.target_key,
            beatmap_id=beatmap_id,
            source=result.source.value,
        )


def _snapshot_to_beatmapset(snapshot: BeatmapsetSnapshot) -> BeatmapSet:
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


__all__ = [
    "BeatmapBlobStorage",
    "FetchBeatmapFileUseCase",
    "FetchBeatmapMetadataUseCase",
]
