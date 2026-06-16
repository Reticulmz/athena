from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileAttachment,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)
from osu_server.repositories.interfaces.beatmap_repository import (
    BeatmapFetchRecord,
    BeatmapFetchTarget,
    BeatmapNotFoundError,
    DuplicateBeatmapChecksumError,
)
from osu_server.repositories.sqlalchemy.models.beatmap import (
    BeatmapFetchStateModel,
    BeatmapFileAttachmentModel,
    BeatmapModel,
    BeatmapSetModel,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.sql.base import Executable


class _BeatmapScalarResult(Protocol):
    def scalar_one_or_none(self) -> object | None: ...

    def scalars(self) -> _BeatmapScalarResult: ...

    def all(self) -> list[object]: ...


class _BeatmapPersistenceSession(Protocol):
    def get(self, model_type: type[object], identity: int) -> Awaitable[object | None]: ...

    def execute(self, statement: Executable) -> Awaitable[_BeatmapScalarResult]: ...

    def merge(self, instance: object) -> Awaitable[object]: ...

    def add(self, instance: object) -> None: ...

    def commit(self) -> Awaitable[None]: ...

    def rollback(self) -> Awaitable[None]: ...

    def refresh(self, instance: object) -> Awaitable[None]: ...


type _BeatmapSessionFactory = Callable[[], AbstractAsyncContextManager[object]]


class SQLAlchemyBeatmapRepository:
    _session_factory: _BeatmapSessionFactory

    def __init__(self, session_factory: _BeatmapSessionFactory) -> None:
        self._session_factory = session_factory

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        async with self._session_factory() as raw_session:
            session = cast("_BeatmapPersistenceSession", raw_session)
            model = await session.get(BeatmapModel, beatmap_id)
            if not isinstance(model, BeatmapModel):
                return None
            attachment = await self._get_current_file_attachment_model(
                session, beatmap_id=beatmap_id
            )
            return _beatmap_to_domain(model, attachment)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        async with self._session_factory() as raw_session:
            session = cast("_BeatmapPersistenceSession", raw_session)
            model = await session.get(BeatmapSetModel, beatmapset_id)
            if not isinstance(model, BeatmapSetModel):
                return None
            beatmap_models = await self._get_beatmap_models_for_set(
                session, beatmapset_id=beatmapset_id
            )
            beatmaps = [
                _beatmap_to_domain(
                    beatmap_model,
                    await self._get_current_file_attachment_model(
                        session, beatmap_id=beatmap_model.id
                    ),
                )
                for beatmap_model in beatmap_models
            ]
            return _beatmapset_to_domain(model, tuple(beatmaps))

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        async with self._session_factory() as raw_session:
            session = cast("_BeatmapPersistenceSession", raw_session)
            stmt = select(BeatmapModel).where(BeatmapModel.checksum_md5 == checksum_md5)
            model = (await session.execute(stmt)).scalar_one_or_none()
            if not isinstance(model, BeatmapModel):
                return None
            attachment = await self._get_current_file_attachment_model(
                session, beatmap_id=model.id
            )
            return _beatmap_to_domain(model, attachment)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        async with self._session_factory() as raw_session:
            session = cast("_BeatmapPersistenceSession", raw_session)
            stmt = (
                select(BeatmapModel)
                .join(
                    BeatmapFileAttachmentModel,
                    BeatmapFileAttachmentModel.beatmap_id == BeatmapModel.id,
                )
                .where(
                    BeatmapModel.beatmapset_id == beatmapset_id,
                    BeatmapFileAttachmentModel.original_filename == original_filename,
                )
                .limit(1)
            )
            model = (await session.execute(stmt)).scalar_one_or_none()
            if not isinstance(model, BeatmapModel):
                return None
            attachment = await self._get_current_file_attachment_model(
                session, beatmap_id=model.id
            )
            return _beatmap_to_domain(model, attachment)

    async def save_beatmapset_snapshot(self, snapshot: BeatmapSet) -> None:
        async with self._session_factory() as raw_session:
            session = cast("_BeatmapPersistenceSession", raw_session)
            _ = await session.merge(_beatmapset_to_model(snapshot))
            try:
                for beatmap in snapshot.beatmaps:
                    existing = await session.get(BeatmapModel, beatmap.id)
                    local_override = (
                        existing.local_status_override
                        if isinstance(existing, BeatmapModel)
                        else beatmap.local_status_override.value
                        if beatmap.local_status_override is not None
                        else None
                    )
                    _ = await session.merge(_beatmap_to_model(beatmap, local_override))
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                conflict = await self._find_conflicting_checksum(session, snapshot)
                checksum_md5 = (
                    conflict[0]
                    if conflict is not None
                    else snapshot.beatmaps[0].checksum_md5
                    if snapshot.beatmaps
                    else ""
                )
                existing_id = conflict[1] if conflict is not None else 0
                raise DuplicateBeatmapChecksumError(
                    checksum_md5=checksum_md5,
                    existing_beatmap_id=existing_id,
                ) from exc

    async def set_local_status_override(
        self, beatmap_id: int, status: LocalBeatmapStatus | None
    ) -> Beatmap:
        async with self._session_factory() as raw_session:
            session = cast("_BeatmapPersistenceSession", raw_session)
            model = await session.get(BeatmapModel, beatmap_id)
            if not isinstance(model, BeatmapModel):
                raise BeatmapNotFoundError(beatmap_id)
            model.local_status_override = status.value if status is not None else None
            await session.commit()
            attachment = await self._get_current_file_attachment_model(
                session, beatmap_id=beatmap_id
            )
            return _beatmap_to_domain(model, attachment)

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        async with self._session_factory() as raw_session:
            session = cast("_BeatmapPersistenceSession", raw_session)
            model = await self._get_current_file_attachment_model(session, beatmap_id=beatmap_id)
            return _attachment_to_domain(model) if model is not None else None

    async def attach_osu_file(self, attachment: BeatmapFileAttachment) -> BeatmapFileAttachment:
        async with self._session_factory() as raw_session:
            session = cast("_BeatmapPersistenceSession", raw_session)
            existing = await self._get_file_attachment_by_key(session, attachment)
            if existing is not None:
                return _attachment_to_domain(existing)

            model = _attachment_to_model(attachment)
            session.add(model)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                existing_after_race = await self._get_file_attachment_by_key(session, attachment)
                if existing_after_race is not None:
                    return _attachment_to_domain(existing_after_race)
                raise BeatmapNotFoundError(attachment.beatmap_id) from exc
            await session.refresh(model)
            return _attachment_to_domain(model)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        async with self._session_factory() as raw_session:
            session = cast("_BeatmapPersistenceSession", raw_session)
            model = await self._get_fetch_state_model(session, target)
            return _fetch_state_to_domain(model) if model is not None else None

    async def try_mark_fetch_pending(self, target: BeatmapFetchTarget, now: datetime) -> bool:
        async with self._session_factory() as raw_session:
            session = cast("_BeatmapPersistenceSession", raw_session)
            model = await self._get_fetch_state_model(session, target)
            if model is not None and model.status == BeatmapFetchState.PENDING_FETCH.value:
                return False
            if model is None:
                model = BeatmapFetchStateModel(
                    target_type=target.target_type,
                    target_key=target.target_key,
                    status=BeatmapFetchState.PENDING_FETCH.value,
                    attempt_count=1,
                    last_error=None,
                    pending_since=now,
                    last_attempted_at=now,
                )
                session.add(model)
            else:
                model.status = BeatmapFetchState.PENDING_FETCH.value
                model.attempt_count += 1
                model.last_error = None
                model.pending_since = now
                model.last_attempted_at = now
            await session.commit()
            return True

    async def mark_fetch_succeeded(self, target: BeatmapFetchTarget, now: datetime) -> None:
        await self._mark_fetch_completed(
            target=target,
            status=BeatmapFetchState.FRESH,
            last_error=None,
            now=now,
        )

    async def mark_fetch_failed(
        self, target: BeatmapFetchTarget, reason: str, now: datetime
    ) -> None:
        await self._mark_fetch_completed(
            target=target,
            status=BeatmapFetchState.FAILED,
            last_error=reason,
            now=now,
        )

    async def _mark_fetch_completed(
        self,
        *,
        target: BeatmapFetchTarget,
        status: BeatmapFetchState,
        last_error: str | None,
        now: datetime,
    ) -> None:
        async with self._session_factory() as raw_session:
            session = cast("_BeatmapPersistenceSession", raw_session)
            model = await self._get_fetch_state_model(session, target)
            if model is None:
                model = BeatmapFetchStateModel(
                    target_type=target.target_type,
                    target_key=target.target_key,
                    status=status.value,
                    attempt_count=0,
                    last_error=last_error,
                    pending_since=None,
                    last_attempted_at=now,
                )
                session.add(model)
            else:
                model.status = status.value
                model.last_error = last_error
                model.pending_since = None
                model.last_attempted_at = now
            await session.commit()

    async def _find_conflicting_checksum(
        self, session: _BeatmapPersistenceSession, snapshot: BeatmapSet
    ) -> tuple[str, int] | None:
        checksums = [b.checksum_md5 for b in snapshot.beatmaps if b.checksum_md5]
        if not checksums:
            return None
        snapshot_ids = {b.id for b in snapshot.beatmaps}
        stmt = select(BeatmapModel).where(BeatmapModel.checksum_md5.in_(checksums))
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            if not isinstance(row, BeatmapModel):
                continue
            if row.id in snapshot_ids:
                continue
            if row.checksum_md5 is None:
                continue
            return (row.checksum_md5, row.id)
        return None

    async def _get_beatmap_models_for_set(
        self, session: _BeatmapPersistenceSession, *, beatmapset_id: int
    ) -> list[BeatmapModel]:
        stmt = select(BeatmapModel).where(BeatmapModel.beatmapset_id == beatmapset_id)
        values = (await session.execute(stmt)).scalars().all()
        return [value for value in values if isinstance(value, BeatmapModel)]

    async def _get_current_file_attachment_model(
        self, session: _BeatmapPersistenceSession, *, beatmap_id: int
    ) -> BeatmapFileAttachmentModel | None:
        stmt = (
            select(BeatmapFileAttachmentModel)
            .where(BeatmapFileAttachmentModel.beatmap_id == beatmap_id)
            .order_by(BeatmapFileAttachmentModel.id.desc())
        )
        model = (await session.execute(stmt)).scalar_one_or_none()
        return model if isinstance(model, BeatmapFileAttachmentModel) else None

    async def _get_file_attachment_by_key(
        self, session: _BeatmapPersistenceSession, attachment: BeatmapFileAttachment
    ) -> BeatmapFileAttachmentModel | None:
        stmt = select(BeatmapFileAttachmentModel).where(
            BeatmapFileAttachmentModel.beatmap_id == attachment.beatmap_id,
            BeatmapFileAttachmentModel.checksum_md5 == attachment.checksum_md5,
        )
        model = (await session.execute(stmt)).scalar_one_or_none()
        return model if isinstance(model, BeatmapFileAttachmentModel) else None

    async def _get_fetch_state_model(
        self, session: _BeatmapPersistenceSession, target: BeatmapFetchTarget
    ) -> BeatmapFetchStateModel | None:
        stmt = select(BeatmapFetchStateModel).where(
            BeatmapFetchStateModel.target_type == target.target_type,
            BeatmapFetchStateModel.target_key == target.target_key,
        )
        model = (await session.execute(stmt)).scalar_one_or_none()
        return model if isinstance(model, BeatmapFetchStateModel) else None


def _beatmapset_to_model(beatmapset: BeatmapSet) -> BeatmapSetModel:
    return BeatmapSetModel(
        id=beatmapset.id,
        artist=beatmapset.artist,
        title=beatmapset.title,
        creator=beatmapset.creator,
        artist_unicode=beatmapset.artist_unicode,
        title_unicode=beatmapset.title_unicode,
        official_status=beatmapset.official_status.value,
        official_status_source=beatmapset.official_status_source.value,
        official_status_verified=(
            beatmapset.official_status_verified is BeatmapSourceVerification.VERIFIED
        ),
        last_fetched_at=beatmapset.last_fetched_at,
        next_refresh_at=beatmapset.next_refresh_at,
    )


def _beatmap_to_model(beatmap: Beatmap, local_status_override: str | None) -> BeatmapModel:
    return BeatmapModel(
        id=beatmap.id,
        beatmapset_id=beatmap.beatmapset_id,
        checksum_md5=beatmap.checksum_md5,
        mode=beatmap.mode,
        version=beatmap.version,
        total_length=beatmap.total_length,
        hit_length=beatmap.hit_length,
        max_combo=beatmap.max_combo,
        bpm=_decimal_or_none(beatmap.bpm),
        cs=_decimal_or_none(beatmap.cs),
        od=_decimal_or_none(beatmap.od),
        ar=_decimal_or_none(beatmap.ar),
        hp=_decimal_or_none(beatmap.hp),
        difficulty_rating=_decimal_or_none(beatmap.difficulty_rating),
        official_status=beatmap.official_status.value,
        official_status_source=beatmap.official_status_source.value,
        official_status_verified=(
            beatmap.official_status_verified is BeatmapSourceVerification.VERIFIED
        ),
        local_status_override=local_status_override,
        last_fetched_at=beatmap.last_fetched_at,
        next_refresh_at=beatmap.next_refresh_at,
    )


def _beatmapset_to_domain(model: BeatmapSetModel, beatmaps: tuple[Beatmap, ...]) -> BeatmapSet:
    return BeatmapSet(
        id=model.id,
        artist=model.artist,
        title=model.title,
        creator=model.creator,
        artist_unicode=model.artist_unicode,
        title_unicode=model.title_unicode,
        official_status=BeatmapRankStatus(model.official_status),
        official_status_source=BeatmapMetadataSource(model.official_status_source),
        official_status_verified=_verification_from_bool(model.official_status_verified),
        beatmaps=beatmaps,
        last_fetched_at=model.last_fetched_at,
        next_refresh_at=model.next_refresh_at,
    )


def _beatmap_to_domain(
    model: BeatmapModel, attachment_model: BeatmapFileAttachmentModel | None
) -> Beatmap:
    attachment = _attachment_to_domain(attachment_model) if attachment_model is not None else None
    return Beatmap(
        id=model.id,
        beatmapset_id=model.beatmapset_id,
        checksum_md5=model.checksum_md5 or "",
        mode=model.mode,
        version=model.version,
        total_length=model.total_length,
        hit_length=model.hit_length,
        max_combo=model.max_combo,
        bpm=float(model.bpm) if model.bpm is not None else None,
        cs=float(model.cs) if model.cs is not None else None,
        od=float(model.od) if model.od is not None else None,
        ar=float(model.ar) if model.ar is not None else None,
        hp=float(model.hp) if model.hp is not None else None,
        difficulty_rating=(
            float(model.difficulty_rating) if model.difficulty_rating is not None else None
        ),
        official_status=BeatmapRankStatus(model.official_status),
        official_status_source=BeatmapMetadataSource(model.official_status_source),
        official_status_verified=_verification_from_bool(model.official_status_verified),
        local_status_override=(
            LocalBeatmapStatus(model.local_status_override)
            if model.local_status_override is not None
            else None
        ),
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=(
            BeatmapFileState.AVAILABLE if attachment is not None else BeatmapFileState.MISSING
        ),
        file_attachment=attachment,
        last_fetched_at=model.last_fetched_at,
        next_refresh_at=model.next_refresh_at,
    )


def _attachment_to_model(attachment: BeatmapFileAttachment) -> BeatmapFileAttachmentModel:
    return BeatmapFileAttachmentModel(
        beatmap_id=attachment.beatmap_id,
        blob_id=attachment.blob_id,
        checksum_md5=attachment.checksum_md5,
        verified_md5=attachment.checksum_md5,
        source=attachment.source,
        original_filename=attachment.original_filename,
        fetched_at=attachment.fetched_at,
        verified_at=attachment.verified_at,
    )


def _attachment_to_domain(model: BeatmapFileAttachmentModel) -> BeatmapFileAttachment:
    return BeatmapFileAttachment(
        beatmap_id=model.beatmap_id,
        blob_id=model.blob_id,
        checksum_md5=model.checksum_md5,
        source=model.source,
        original_filename=model.original_filename,
        fetched_at=model.fetched_at,
        verified_at=model.verified_at,
        id=model.id,
    )


def _fetch_state_to_domain(model: BeatmapFetchStateModel) -> BeatmapFetchRecord:
    return BeatmapFetchRecord(
        target=BeatmapFetchTarget(target_type=model.target_type, target_key=model.target_key),
        status=BeatmapFetchState(model.status),
        attempt_count=model.attempt_count,
        last_error=model.last_error,
        pending_since=model.pending_since,
        last_attempted_at=model.last_attempted_at,
    )


def _verification_from_bool(is_verified: bool) -> BeatmapSourceVerification:
    return (
        BeatmapSourceVerification.VERIFIED if is_verified else BeatmapSourceVerification.UNVERIFIED
    )


def _decimal_or_none(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
