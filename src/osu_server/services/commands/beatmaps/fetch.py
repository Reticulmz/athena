"""Beatmap fetch command use-cases."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, cast

import structlog

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileAttachment,
    BeatmapFileState,
    BeatmapMetadataLookupKind,
    BeatmapSet,
)
from osu_server.shared.ports import (
    BeatmapLeaderboardRebuildWorkerWake,
    NoopBeatmapLeaderboardRebuildWorkerWake,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        BeatmapFileProvider,
        BeatmapFreshnessPolicy,
        BeatmapMetadataProvider,
        BeatmapsetSnapshot,
    )
    from osu_server.domain.storage.blobs import BlobStoreResult
    from osu_server.repositories.interfaces.commands.beatmaps import (
        BeatmapCommandRepository,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))

_OSU_BEATMAP_CONTENT_TYPE = "application/x-osu-beatmap"


class BeatmapBlobStorage(Protocol):
    async def put_bytes(
        self,
        data: bytes,
        *,
        content_type: str,
    ) -> BlobStoreResult: ...


class FetchBeatmapMetadataUseCase:
    """beatmap metadata を provider から取得し DB cache を更新する use-case。"""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        metadata_provider: BeatmapMetadataProvider,
        freshness_policy: BeatmapFreshnessPolicy,
        official_sources_available: bool = True,
        leaderboard_rebuild_wake: BeatmapLeaderboardRebuildWorkerWake | None = None,
    ) -> None:
        """依存関係と cache freshness 判定条件を設定する。"""
        self._uow_factory: UnitOfWorkFactory = uow_factory
        self._provider: BeatmapMetadataProvider = metadata_provider
        self._freshness_policy: BeatmapFreshnessPolicy = freshness_policy
        self._official_sources_available: bool = official_sources_available
        self._leaderboard_rebuild_wake: BeatmapLeaderboardRebuildWorkerWake = (
            leaderboard_rebuild_wake or NoopBeatmapLeaderboardRebuildWorkerWake()
        )

    async def execute(self, target: BeatmapFetchTarget) -> None:
        """target の metadata fetch を冪等に実行する。"""
        now = datetime.now(UTC)

        async with self._uow_factory() as uow:
            previous_fetch_record = await uow.beatmaps.get_fetch_state(target)
            acquired = await uow.beatmaps.try_mark_fetch_pending(target, now)
            if not acquired:
                logger.debug(
                    "beatmap_fetch_already_pending",
                    target_type=target.target_type,
                    target_key=target.target_key,
                )
                return
            if await self._has_reusable_cached_metadata(
                uow.beatmaps,
                target,
                now,
                previous_fetch_failed=previous_fetch_record is not None
                and previous_fetch_record.status is BeatmapFetchState.FAILED,
            ):
                await uow.beatmaps.mark_fetch_succeeded(target, now)
                await uow.commit()
                logger.info(
                    "beatmap_metadata_fetch_cache_hit",
                    target_type=target.target_type,
                    target_key=target.target_key,
                )
                return
            await uow.commit()

        logger.info(
            "beatmap_metadata_fetch_started",
            target_type=target.target_type,
            target_key=target.target_key,
        )

        try:
            snapshot = await self._lookup(target)
        except ValueError as exc:
            await self._mark_failed(
                target=target,
                error=str(exc),
                now=now,
            )
            logger.exception(
                "beatmap_metadata_fetch_failed",
                target_type=target.target_type,
                target_key=target.target_key,
                error=str(exc),
            )
            return

        if snapshot is None:
            await self._mark_failed(
                target=target,
                error="all configured metadata providers returned no result",
                now=now,
            )
            logger.error(
                "beatmap_metadata_fetch_failed",
                target_type=target.target_type,
                target_key=target.target_key,
                error="all configured metadata providers returned no result",
            )
            return

        beatmapset = _snapshot_to_beatmapset(snapshot)
        async with self._uow_factory() as uow:
            previous_beatmapset = await uow.beatmaps.get_beatmapset(beatmapset.id)
            rebuild_reason = _leaderboard_rebuild_reason(previous_beatmapset, beatmapset)
            await uow.beatmaps.save_beatmapset_snapshot(beatmapset)
            await uow.beatmaps.mark_fetch_succeeded(target, now)
            await uow.commit()

        if rebuild_reason is not None:
            try:
                await self._leaderboard_rebuild_wake.wake_beatmapset_rebuild(
                    beatmapset_id=beatmapset.id,
                    reason=rebuild_reason,
                )
            except Exception as exc:
                logger.error(
                    "beatmap_leaderboard_rebuild_enqueue_failed",
                    target_type=target.target_type,
                    target_key=target.target_key,
                    beatmapset_id=beatmapset.id,
                    reason=rebuild_reason,
                    error=str(exc),
                    exc_info=True,
                )

        logger.info(
            "beatmap_metadata_fetch_succeeded",
            target_type=target.target_type,
            target_key=target.target_key,
            beatmapset_id=snapshot.beatmapset_id,
            source=snapshot.official_status_source.value,
            verified=(snapshot.official_status_verified.value == "verified"),
        )

    async def _has_reusable_cached_metadata(
        self,
        repository: BeatmapCommandRepository,
        target: BeatmapFetchTarget,
        now: datetime,
        *,
        previous_fetch_failed: bool = False,
    ) -> bool:
        if target.force_refresh:
            return False
        if previous_fetch_failed:
            return False

        cached_beatmaps = await self._cached_beatmaps_for_target(repository, target)
        if not cached_beatmaps:
            return False

        return all(
            not self._freshness_policy.evaluate(
                beatmap,
                now=now,
                official_sources_available=self._official_sources_available,
            ).should_refresh
            for beatmap in cached_beatmaps
        )

    async def _cached_beatmaps_for_target(
        self,
        repository: BeatmapCommandRepository,
        target: BeatmapFetchTarget,
    ) -> tuple[Beatmap, ...]:
        try:
            lookup = target.metadata_lookup_target()
            if lookup.kind is BeatmapMetadataLookupKind.BEATMAP_ID:
                beatmap = await repository.get_beatmap(lookup.int_value())
                return () if beatmap is None else (beatmap,)
            if lookup.kind is BeatmapMetadataLookupKind.BEATMAPSET_ID:
                beatmapset = await repository.get_beatmapset(lookup.int_value())
                return () if beatmapset is None else beatmapset.beatmaps
        except ValueError:
            return ()

        if lookup.kind is BeatmapMetadataLookupKind.CHECKSUM:
            beatmap = await repository.get_beatmap_by_checksum(lookup.value)
            return () if beatmap is None else (beatmap,)
        return ()

    async def _lookup(self, target: BeatmapFetchTarget) -> BeatmapsetSnapshot | None:
        lookup = target.metadata_lookup_target()
        if lookup.kind is BeatmapMetadataLookupKind.BEATMAP_ID:
            return await self._provider.lookup_by_beatmap_id(lookup.int_value())
        if lookup.kind is BeatmapMetadataLookupKind.BEATMAPSET_ID:
            return await self._provider.lookup_by_beatmapset_id(lookup.int_value())
        if lookup.kind is BeatmapMetadataLookupKind.CHECKSUM:
            return await self._provider.lookup_by_checksum(lookup.value)
        msg = f"unsupported metadata lookup kind: {lookup.kind}"
        raise ValueError(msg)

    async def _mark_failed(
        self,
        *,
        target: BeatmapFetchTarget,
        error: str,
        now: datetime,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.beatmaps.mark_fetch_failed(target, error, now)
            await uow.commit()


class FetchBeatmapFileUseCase:
    """Fetch and verify a .osu file idempotently, then attach it as a blob."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        file_provider: BeatmapFileProvider,
        blob_storage: BeatmapBlobStorage,
    ) -> None:
        self._uow_factory: UnitOfWorkFactory = uow_factory
        self._provider: BeatmapFileProvider = file_provider
        self._blob: BeatmapBlobStorage = blob_storage

    async def execute(self, target: BeatmapFetchTarget) -> None:
        """Run the idempotent file fetch cycle for *target*."""
        now = datetime.now(UTC)

        async with self._uow_factory() as uow:
            acquired = await uow.beatmaps.try_mark_fetch_pending(target, now)
            if acquired:
                await uow.commit()
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

        try:
            beatmap_id = target.file_beatmap_id()
        except ValueError as exc:
            await self._mark_failed(
                target=target,
                error=str(exc),
                now=now,
            )
            logger.exception(
                "beatmap_file_fetch_failed",
                target_type=target.target_type,
                target_key=target.target_key,
                error=str(exc),
            )
            return

        async with self._uow_factory() as uow:
            beatmap = await uow.beatmaps.get_beatmap(beatmap_id)
        if beatmap is None:
            await self._mark_failed(
                target=target,
                error=f"beatmap {beatmap_id} not found in repository",
                now=now,
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
        async with self._uow_factory() as uow:
            existing_attachment = await uow.beatmaps.get_current_file_attachment(beatmap_id)
        if existing_attachment is not None and existing_attachment.checksum_md5 == expected_md5:
            await self._mark_succeeded(target=target, now=now)
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
            await self._mark_failed(
                target=target,
                error=f"{type(exc).__name__}: {exc}",
                now=now,
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
            await self._mark_failed(
                target=target,
                error=f"checksum mismatch: expected {expected_md5}, got {fetched_md5}",
                now=now,
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
        async with self._uow_factory() as uow:
            _ = await uow.beatmaps.attach_osu_file(attachment)
            await uow.beatmaps.mark_fetch_succeeded(target, now)
            await uow.commit()

        logger.info(
            "beatmap_file_fetch_succeeded",
            target_type=target.target_type,
            target_key=target.target_key,
            beatmap_id=beatmap_id,
            source=result.source.value,
        )

    async def _mark_failed(
        self,
        *,
        target: BeatmapFetchTarget,
        error: str,
        now: datetime,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.beatmaps.mark_fetch_failed(target, error, now)
            await uow.commit()

    async def _mark_succeeded(self, *, target: BeatmapFetchTarget, now: datetime) -> None:
        async with self._uow_factory() as uow:
            await uow.beatmaps.mark_fetch_succeeded(target, now)
            await uow.commit()


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
            official_last_updated_at=bm.official_last_updated_at,
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


def _leaderboard_rebuild_reason(
    previous: BeatmapSet | None,
    current: BeatmapSet,
) -> str | None:
    if previous is None:
        return None

    previous_by_id = {beatmap.id: beatmap for beatmap in previous.beatmaps}
    for beatmap in current.beatmaps:
        previous_beatmap = previous_by_id.get(beatmap.id)
        if previous_beatmap is None:
            continue
        if previous_beatmap.effective_status is not beatmap.effective_status:
            return "beatmap_status_changed"

    for beatmap in current.beatmaps:
        previous_beatmap = previous_by_id.get(beatmap.id)
        if previous_beatmap is None:
            continue
        if previous_beatmap.checksum_md5 != beatmap.checksum_md5:
            return "beatmap_checksum_changed"

    return None


__all__ = [
    "BeatmapBlobStorage",
    "FetchBeatmapFileUseCase",
    "FetchBeatmapMetadataUseCase",
]
