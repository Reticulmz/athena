"""Shared helpers for SQLAlchemy query repositories."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from typing import TYPE_CHECKING

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
from osu_server.domain.chat.channels import Channel, ChannelRoleOverride, ChannelType
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.users import User
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, PlayTimeSource, Ruleset, Score
from osu_server.domain.storage.blobs import Blob, BlobStorageBackendKind

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from osu_server.repositories.sqlalchemy.models.beatmap import (
        BeatmapFetchStateModel,
        BeatmapFileAttachmentModel,
        BeatmapModel,
        BeatmapSetModel,
    )
    from osu_server.repositories.sqlalchemy.models.blob import BlobModel
    from osu_server.repositories.sqlalchemy.models.channel import (
        ChannelModel,
        ChannelRoleOverrideModel,
    )
    from osu_server.repositories.sqlalchemy.models.role import RoleModel
    from osu_server.repositories.sqlalchemy.models.score import ScoreModel
    from osu_server.repositories.sqlalchemy.models.user import UserModel

type SQLAlchemyQuerySessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def user_to_domain(model: UserModel) -> User:
    return User(
        id=model.id,
        username=model.username,
        safe_username=model.safe_username,
        email=model.email,
        password_hash=model.password_hash,
        country=model.country,
        created_at=model.created_at,
        updated_at=model.updated_at,
        latest_activity_at=model.latest_activity_at,
    )


def role_to_domain(model: RoleModel) -> Role:
    return Role(
        id=model.id,
        name=model.name,
        permissions=Privileges(model.permissions),
        position=model.position,
    )


def channel_to_domain(model: ChannelModel) -> Channel:
    return Channel(
        id=model.id,
        name=model.name,
        topic=model.topic,
        channel_type=ChannelType(model.channel_type),
        auto_join=model.auto_join,
        rate_limit_messages=model.rate_limit_messages,
        rate_limit_window=model.rate_limit_window,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def channel_override_to_domain(model: ChannelRoleOverrideModel) -> ChannelRoleOverride:
    return ChannelRoleOverride(
        channel_id=model.channel_id,
        role_id=model.role_id,
        can_read=model.can_read,
        can_write=model.can_write,
    )


def score_to_domain(model: ScoreModel) -> Score:
    return Score(
        id=model.id,
        user_id=model.user_id,
        beatmap_id=model.beatmap_id,
        beatmap_checksum=model.beatmap_checksum,
        online_checksum=model.online_checksum,
        ruleset=Ruleset(model.ruleset),
        playstyle=Playstyle(model.playstyle),
        mods=ModCombination.from_persistence_bitmask(model.mods),
        n300=model.n300,
        n100=model.n100,
        n50=model.n50,
        geki=model.geki,
        katu=model.katu,
        miss=model.miss,
        score=model.score,
        max_combo=model.max_combo,
        accuracy=model.accuracy,
        grade=Grade(model.grade),
        passed=model.passed,
        perfect=model.perfect,
        client_version=model.client_version,
        submitted_at=model.submitted_at,
        beatmap_status_at_submission=(
            BeatmapRankStatus(model.beatmap_status_at_submission)
            if model.beatmap_status_at_submission is not None
            else None
        ),
        leaderboard_eligible_at_submission=model.leaderboard_eligible_at_submission,
        fail_time_ms=model.fail_time_ms,
        play_time_seconds=model.play_time_seconds,
        play_time_source=(
            PlayTimeSource(model.play_time_source) if model.play_time_source is not None else None
        ),
        submit_exit_classification=model.submit_exit_classification,
        replay_view_count=model.replay_view_count,
    )


def blob_to_domain(model: BlobModel) -> Blob:
    return Blob(
        id=model.id,
        sha256=model.sha256,
        byte_size=model.byte_size,
        content_type=model.content_type,
        storage_backend=BlobStorageBackendKind(model.storage_backend),
        storage_key=model.storage_key,
        created_at=model.created_at,
    )


def beatmapset_to_domain(model: BeatmapSetModel, beatmaps: tuple[Beatmap, ...]) -> BeatmapSet:
    return BeatmapSet(
        id=model.id,
        artist=model.artist,
        title=model.title,
        creator=model.creator,
        artist_unicode=model.artist_unicode,
        title_unicode=model.title_unicode,
        official_status=BeatmapRankStatus(model.official_status),
        official_status_source=BeatmapMetadataSource(model.official_status_source),
        official_status_verified=verification_from_bool(model.official_status_verified),
        beatmaps=beatmaps,
        last_fetched_at=model.last_fetched_at,
        next_refresh_at=model.next_refresh_at,
    )


def beatmap_to_domain(
    model: BeatmapModel, attachment_model: BeatmapFileAttachmentModel | None
) -> Beatmap:
    attachment = attachment_to_domain(attachment_model) if attachment_model is not None else None
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
        official_status_verified=verification_from_bool(model.official_status_verified),
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


def attachment_to_domain(model: BeatmapFileAttachmentModel) -> BeatmapFileAttachment:
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


def fetch_state_to_domain(model: BeatmapFetchStateModel) -> BeatmapFetchRecord:
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


def verification_from_bool(is_verified: bool) -> BeatmapSourceVerification:
    return (
        BeatmapSourceVerification.VERIFIED if is_verified else BeatmapSourceVerification.UNVERIFIED
    )


def decimal_or_none(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))
