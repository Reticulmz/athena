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

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Protocol, cast

import structlog
from taskiq import Context, TaskiqDepends

from osu_server.domain.beatmaps import BeatmapFileAttachment
from osu_server.infrastructure.jobs.registry import jobs
from osu_server.repositories.interfaces.beatmap_repository import BeatmapFetchTarget

if TYPE_CHECKING:
    from taskiq import TaskiqState

    from osu_server.domain.beatmaps import (
        BeatmapFileProvider,
        BeatmapMetadataProvider,
        BeatmapSet,
        BeatmapsetSnapshot,
    )
    from osu_server.domain.storage.blobs import BlobStoreResult
    from osu_server.repositories.interfaces.beatmap_repository import (
        BeatmapRepository,
    )

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class BeatmapBlobStorage(Protocol):
    async def put_bytes(
        self,
        data: bytes,
        *,
        content_type: str,
    ) -> BlobStoreResult: ...


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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _snapshot_to_beatmapset(snapshot: BeatmapsetSnapshot) -> BeatmapSet:
    """Convert a provider snapshot to a domain ``BeatmapSet``."""
    from osu_server.domain.beatmaps import (  # noqa: PLC0415
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


class FetchBeatmapFileJob:
    """Fetch and verify a .osu file idempotently, then attach as a blob.

    The job marks the target as pending, fetches the .osu file bytes through
    a ``BeatmapFileProvider`` (typically the composite official+mirror
    provider), verifies the md5 checksum against the expected value from
    beatmap metadata, stores the verified bytes via ``BlobStorageService``,
    and attaches the blob to the beatmap.

    If the target is already pending, the job is a no-op.
    """

    def __init__(
        self,
        *,
        repository: BeatmapRepository,
        file_provider: BeatmapFileProvider,
        blob_storage: BeatmapBlobStorage,
    ) -> None:
        self._repo: BeatmapRepository = repository
        self._provider: BeatmapFileProvider = file_provider
        self._blob: BeatmapBlobStorage = blob_storage

    async def execute(self, target: BeatmapFetchTarget) -> None:
        """Run the idempotent fetch-and-attach cycle for *target*."""
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
            content_type="application/x-osu-beatmap",
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


# ---------------------------------------------------------------------------
# Worker runtime Protocols -- taskiq job adapters
# ---------------------------------------------------------------------------


class WorkerBeatmapMetadataFetch(Protocol):
    """Beatmap metadata fetch use-case surface required by job adapters."""

    async def execute(self, target: BeatmapFetchTarget) -> None: ...


class WorkerBeatmapFileFetch(Protocol):
    """Beatmap file fetch use-case surface required by job adapters."""

    async def execute(self, target: BeatmapFetchTarget) -> None: ...


def get_beatmap_metadata_fetch(state: TaskiqState) -> WorkerBeatmapMetadataFetch | None:
    """Return the beatmap metadata fetch service stored in taskiq state."""
    return cast(
        "WorkerBeatmapMetadataFetch | None",
        getattr(state, "beatmap_metadata_fetch", None),
    )


def get_beatmap_file_fetch(state: TaskiqState) -> WorkerBeatmapFileFetch | None:
    """Return the beatmap file fetch service stored in taskiq state."""
    return cast(
        "WorkerBeatmapFileFetch | None",
        getattr(state, "beatmap_file_fetch", None),
    )


@jobs.register(task_name="fetch_beatmap_metadata")
async def fetch_beatmap_metadata(
    target_type: str,
    target_key: str,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Taskiq adapter for ``FetchBeatmapMetadataJob``.

    Converts serialised string parameters back to a ``BeatmapFetchTarget``
    and delegates to the worker-side job instance.
    """
    job = get_beatmap_metadata_fetch(context.state)
    if job is None:
        logger.error(
            "beatmap_metadata_fetch_runtime_unavailable",
            task_name="fetch_beatmap_metadata",
            target_type=target_type,
            target_key=target_key,
        )
        return
    target = BeatmapFetchTarget(target_type=target_type, target_key=target_key)
    await job.execute(target)


@jobs.register(task_name="fetch_beatmap_file")
async def fetch_beatmap_file(
    target_type: str,
    target_key: str,
    context: Annotated[Context, TaskiqDepends()],
) -> None:
    """Taskiq adapter for ``FetchBeatmapFileJob``.

    Converts serialised string parameters back to a ``BeatmapFetchTarget``
    and delegates to the worker-side job instance.
    """
    job = get_beatmap_file_fetch(context.state)
    if job is None:
        logger.error(
            "beatmap_file_fetch_runtime_unavailable",
            task_name="fetch_beatmap_file",
            target_type=target_type,
            target_key=target_key,
        )
        return
    target = BeatmapFetchTarget(target_type=target_type, target_key=target_key)
    await job.execute(target)


__all__ = [
    "FetchBeatmapFileJob",
    "FetchBeatmapMetadataJob",
    "WorkerBeatmapFileFetch",
    "WorkerBeatmapMetadataFetch",
    "fetch_beatmap_file",
    "fetch_beatmap_metadata",
    "get_beatmap_file_fetch",
    "get_beatmap_metadata_fetch",
]
