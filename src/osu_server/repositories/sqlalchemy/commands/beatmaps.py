"""SQLAlchemy command-side beatmap repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from sqlalchemy import func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchRecord,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFetchTargetKind,
    BeatmapFileAttachment,
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)
from osu_server.repositories.interfaces.commands.beatmaps import BeatmapSubmissionCounts
from osu_server.repositories.sqlalchemy.models.beatmap import (
    BeatmapFetchStateModel,
    BeatmapFileAttachmentModel,
    BeatmapModel,
    BeatmapSetModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.dml import ReturningInsert


class DuplicateBeatmapChecksumError(ValueError):
    """Raised when one checksum is assigned to multiple beatmaps."""

    checksum_md5: str
    existing_beatmap_id: int

    def __init__(self, *, checksum_md5: str, existing_beatmap_id: int) -> None:
        self.checksum_md5 = checksum_md5
        self.existing_beatmap_id = existing_beatmap_id
        super().__init__(
            f"checksum {checksum_md5} already belongs to beatmap {existing_beatmap_id}"
        )


class BeatmapNotFoundError(LookupError):
    """Raised when a beatmap command requires an unknown beatmap."""

    beatmap_id: int

    def __init__(self, beatmap_id: int) -> None:
        self.beatmap_id = beatmap_id
        super().__init__(f"beatmap {beatmap_id} was not found")


class SQLAlchemyBeatmapCommandRepository:
    """Beatmap command repository backed by a UoW-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        model = await self._session.get(BeatmapModel, beatmap_id)
        if not isinstance(model, BeatmapModel):
            return None
        attachment = await self._get_current_file_attachment_model(beatmap_id=beatmap_id)
        return _beatmap_to_domain(model, attachment)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        model = await self._session.get(BeatmapSetModel, beatmapset_id)
        if not isinstance(model, BeatmapSetModel):
            return None

        beatmap_models = await self._get_beatmap_models_for_set(beatmapset_id=beatmapset_id)
        beatmaps = [
            _beatmap_to_domain(
                beatmap_model,
                await self._get_current_file_attachment_model(beatmap_id=beatmap_model.id),
            )
            for beatmap_model in beatmap_models
        ]
        return _beatmapset_to_domain(model, tuple(beatmaps))

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        model = (
            await self._session.execute(
                select(BeatmapModel).where(BeatmapModel.checksum_md5 == checksum_md5)
            )
        ).scalar_one_or_none()
        if not isinstance(model, BeatmapModel):
            return None
        attachment = await self._get_current_file_attachment_model(beatmap_id=model.id)
        return _beatmap_to_domain(model, attachment)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        model = (
            await self._session.execute(
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
        ).scalar_one_or_none()
        if not isinstance(model, BeatmapModel):
            return None
        attachment = await self._get_current_file_attachment_model(beatmap_id=model.id)
        return _beatmap_to_domain(model, attachment)

    async def save_beatmapset_snapshot(self, snapshot: BeatmapSet) -> None:
        await self._check_checksum_conflicts(snapshot)
        _ = await self._session.merge(_beatmapset_to_model(snapshot))
        try:
            for beatmap in snapshot.beatmaps:
                existing = await self._session.get(BeatmapModel, beatmap.id)
                local_override = (
                    existing.local_status_override
                    if isinstance(existing, BeatmapModel)
                    else beatmap.local_status_override.value
                    if beatmap.local_status_override is not None
                    else None
                )
                local_override_changed_at = (
                    existing.local_status_override_changed_at
                    if isinstance(existing, BeatmapModel)
                    else beatmap.local_status_override_changed_at
                )
                official_last_updated_at = (
                    beatmap.official_last_updated_at
                    if beatmap.official_last_updated_at is not None
                    else existing.official_last_updated_at
                    if isinstance(existing, BeatmapModel)
                    else None
                )
                play_count = (
                    _existing_count(existing.play_count)
                    if isinstance(existing, BeatmapModel)
                    else 0
                )
                pass_count = (
                    _existing_count(existing.pass_count)
                    if isinstance(existing, BeatmapModel)
                    else 0
                )
                stored_beatmap = replace(
                    beatmap,
                    official_last_updated_at=official_last_updated_at,
                )
                _ = await self._session.merge(
                    _beatmap_to_model(
                        stored_beatmap,
                        local_override,
                        local_override_changed_at,
                        play_count,
                        pass_count,
                    )
                )
            await self._session.flush()
        except IntegrityError as exc:
            checksum_md5 = snapshot.beatmaps[0].checksum_md5 if snapshot.beatmaps else ""
            raise DuplicateBeatmapChecksumError(
                checksum_md5=checksum_md5,
                existing_beatmap_id=0,
            ) from exc

    async def set_local_status_override(
        self, beatmap_id: int, status: LocalBeatmapStatus | None
    ) -> Beatmap:
        model = await self._session.get(BeatmapModel, beatmap_id)
        if not isinstance(model, BeatmapModel):
            raise BeatmapNotFoundError(beatmap_id)

        new_status = status.value if status is not None else None
        if model.local_status_override != new_status:
            model.local_status_override = new_status
            model.local_status_override_changed_at = (
                datetime.now(UTC) if new_status is not None else None
            )
        elif new_status is not None and model.local_status_override_changed_at is None:
            model.local_status_override_changed_at = datetime.now(UTC)
        await self._session.flush()
        attachment = await self._get_current_file_attachment_model(beatmap_id=beatmap_id)
        return _beatmap_to_domain(model, attachment)

    async def increment_submission_counts(
        self,
        beatmap_id: int,
        *,
        passed: bool,
    ) -> BeatmapSubmissionCounts:
        result = await self._session.execute(
            _increment_submission_counts_statement(beatmap_id, passed=passed)
        )
        row = result.one_or_none()
        if row is None:
            raise BeatmapNotFoundError(beatmap_id)
        play_count, pass_count = cast("tuple[object, object]", cast("object", row))
        return BeatmapSubmissionCounts(
            play_count=_count_value(play_count),
            pass_count=_count_value(pass_count),
        )

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        model = await self._get_current_file_attachment_model(beatmap_id=beatmap_id)
        return _attachment_to_domain(model) if model is not None else None

    async def attach_osu_file(self, attachment: BeatmapFileAttachment) -> BeatmapFileAttachment:
        beatmap = await self._session.get(BeatmapModel, attachment.beatmap_id)
        if not isinstance(beatmap, BeatmapModel):
            raise BeatmapNotFoundError(attachment.beatmap_id)

        existing = await self._get_file_attachment_by_key(attachment)
        if existing is not None:
            return _attachment_to_domain(existing)

        model = _attachment_to_model(attachment)
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise BeatmapNotFoundError(attachment.beatmap_id) from exc
        await self._session.refresh(model)
        return _attachment_to_domain(model)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        model = await self._get_fetch_state_model(target)
        return _fetch_state_to_domain(model) if model is not None else None

    async def try_mark_fetch_pending(self, target: BeatmapFetchTarget, now: datetime) -> bool:
        """fetch target を pending_fetch に atomically 遷移する.

        Args:
            target: fetch state の対象.
            now: pending_since/last_attempted_at に保存する時刻.

        Returns:
            この呼び出しが fetch lock を取得した場合は True. 既に pending_fetch
            の場合は False.

        Raises:
            SQLAlchemy 由来の永続化例外を上位へ送出する.

        Constraints:
            PostgreSQL の ON CONFLICT で判定し, 並列 INSERT 競合を起こさない.
        """
        result = await self._session.execute(_mark_fetch_pending_statement(target, now))
        row_id = result.scalar_one_or_none()
        if row_id is None:
            return False
        _ = await self._session.get(
            BeatmapFetchStateModel,
            row_id,
            populate_existing=True,
        )
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
        model = await self._get_fetch_state_model(target)
        if model is None:
            model = BeatmapFetchStateModel(
                target_type=target.kind.value,
                target_key=target.target_key,
                status=status.value,
                attempt_count=0,
                last_error=last_error,
                pending_since=None,
                last_attempted_at=now,
            )
            self._session.add(model)
        else:
            model.status = status.value
            model.last_error = last_error
            model.pending_since = None
            model.last_attempted_at = now
        await self._session.flush()

    async def _check_checksum_conflicts(self, snapshot: BeatmapSet) -> None:
        incoming_beatmap_ids_by_checksum: dict[str, int] = {}
        for beatmap in snapshot.beatmaps:
            incoming_beatmap_id = incoming_beatmap_ids_by_checksum.get(beatmap.checksum_md5)
            if incoming_beatmap_id is not None and incoming_beatmap_id != beatmap.id:
                raise DuplicateBeatmapChecksumError(
                    checksum_md5=beatmap.checksum_md5,
                    existing_beatmap_id=incoming_beatmap_id,
                )
            incoming_beatmap_ids_by_checksum[beatmap.checksum_md5] = beatmap.id

            existing = (
                await self._session.execute(
                    select(BeatmapModel).where(BeatmapModel.checksum_md5 == beatmap.checksum_md5)
                )
            ).scalar_one_or_none()
            if isinstance(existing, BeatmapModel) and existing.id != beatmap.id:
                raise DuplicateBeatmapChecksumError(
                    checksum_md5=beatmap.checksum_md5,
                    existing_beatmap_id=existing.id,
                )

    async def _get_beatmap_models_for_set(self, *, beatmapset_id: int) -> list[BeatmapModel]:
        return list(
            (
                await self._session.execute(
                    select(BeatmapModel).where(BeatmapModel.beatmapset_id == beatmapset_id)
                )
            )
            .scalars()
            .all()
        )

    async def _get_current_file_attachment_model(
        self, *, beatmap_id: int
    ) -> BeatmapFileAttachmentModel | None:
        model = (
            await self._session.execute(
                select(BeatmapFileAttachmentModel)
                .where(BeatmapFileAttachmentModel.beatmap_id == beatmap_id)
                .order_by(BeatmapFileAttachmentModel.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return model if isinstance(model, BeatmapFileAttachmentModel) else None

    async def _get_file_attachment_by_key(
        self, attachment: BeatmapFileAttachment
    ) -> BeatmapFileAttachmentModel | None:
        model = (
            await self._session.execute(
                select(BeatmapFileAttachmentModel).where(
                    BeatmapFileAttachmentModel.beatmap_id == attachment.beatmap_id,
                    BeatmapFileAttachmentModel.checksum_md5 == attachment.checksum_md5,
                )
            )
        ).scalar_one_or_none()
        return model if isinstance(model, BeatmapFileAttachmentModel) else None

    async def _get_fetch_state_model(
        self, target: BeatmapFetchTarget
    ) -> BeatmapFetchStateModel | None:
        model = (
            await self._session.execute(
                select(BeatmapFetchStateModel).where(
                    BeatmapFetchStateModel.target_type == target.kind.value,
                    BeatmapFetchStateModel.target_key == target.target_key,
                )
            )
        ).scalar_one_or_none()
        return model if isinstance(model, BeatmapFetchStateModel) else None


def _mark_fetch_pending_statement(
    target: BeatmapFetchTarget,
    now: datetime,
) -> ReturningInsert[tuple[int]]:
    insert_statement = insert(BeatmapFetchStateModel).values(
        target_type=target.kind.value,
        target_key=target.target_key,
        status=BeatmapFetchState.PENDING_FETCH.value,
        attempt_count=1,
        last_error=None,
        pending_since=now,
        last_attempted_at=now,
    )
    return insert_statement.on_conflict_do_update(
        index_elements=[
            BeatmapFetchStateModel.target_type,
            BeatmapFetchStateModel.target_key,
        ],
        set_={
            "status": BeatmapFetchState.PENDING_FETCH.value,
            "attempt_count": BeatmapFetchStateModel.attempt_count + 1,
            "last_error": None,
            "pending_since": now,
            "last_attempted_at": now,
            "updated_at": func.now(),
        },
        where=BeatmapFetchStateModel.status != BeatmapFetchState.PENDING_FETCH.value,
    ).returning(BeatmapFetchStateModel.id)


def _increment_submission_counts_statement(beatmap_id: int, *, passed: bool):
    pass_increment = 1 if passed else 0
    return (
        update(BeatmapModel)
        .where(BeatmapModel.id == beatmap_id)
        .values(
            play_count=BeatmapModel.play_count + literal(1),
            pass_count=BeatmapModel.pass_count + literal(pass_increment),
            updated_at=func.now(),
        )
        .returning(BeatmapModel.play_count, BeatmapModel.pass_count)
    )


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


def _beatmap_to_model(
    beatmap: Beatmap,
    local_status_override: str | None,
    local_status_override_changed_at: datetime | None,
    play_count: int,
    pass_count: int,
) -> BeatmapModel:
    return BeatmapModel(
        id=beatmap.id,
        beatmapset_id=beatmap.beatmapset_id,
        checksum_md5=beatmap.checksum_md5,
        mode=beatmap.mode.value,
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
        local_status_override_changed_at=local_status_override_changed_at,
        play_count=play_count,
        pass_count=pass_count,
        official_last_updated_at=beatmap.official_last_updated_at,
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
        mode=BeatmapMode(model.mode),
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
        official_last_updated_at=model.official_last_updated_at,
        local_status_override_changed_at=model.local_status_override_changed_at,
    )


def _attachment_to_model(attachment: BeatmapFileAttachment) -> BeatmapFileAttachmentModel:
    return BeatmapFileAttachmentModel(
        beatmap_id=attachment.beatmap_id,
        blob_id=attachment.blob_id,
        checksum_md5=attachment.checksum_md5,
        verified_md5=attachment.checksum_md5,
        source=attachment.source.value,
        original_filename=attachment.original_filename,
        fetched_at=attachment.fetched_at,
        verified_at=attachment.verified_at,
    )


def _attachment_to_domain(model: BeatmapFileAttachmentModel) -> BeatmapFileAttachment:
    return BeatmapFileAttachment(
        beatmap_id=model.beatmap_id,
        blob_id=model.blob_id,
        checksum_md5=model.checksum_md5,
        source=BeatmapFileSource(model.source),
        original_filename=model.original_filename,
        fetched_at=model.fetched_at,
        verified_at=model.verified_at,
        id=model.id,
    )


def _fetch_state_to_domain(model: BeatmapFetchStateModel) -> BeatmapFetchRecord:
    return BeatmapFetchRecord(
        target=BeatmapFetchTarget(
            target_type=BeatmapFetchTargetKind(model.target_type),
            target_key=model.target_key,
        ),
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


def _count_value(value: object) -> int:
    if not isinstance(value, int):
        msg = f"expected integer count value, got {type(value).__name__}"
        raise TypeError(msg)
    return value


def _existing_count(value: object) -> int:
    if value is None:
        return 0
    return _count_value(value)
