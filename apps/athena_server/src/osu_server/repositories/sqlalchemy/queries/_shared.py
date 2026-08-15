"""SQLAlchemy query repositoryが永続modelをdomain valueへ変換する共通helperを提供する."""

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
    """永続化されたUser modelをdomain Userへ変換する.

    Args:
        model (UserModel): User tableから取得済みの永続model.

    Returns:
        User: 永続fieldを転記したdomain User.

    Notes:
        modelの値は検証または正規化せず,read modelとしてそのまま転記する.
    """
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
    """永続化されたRole modelをdomain Roleへ変換する.

    Args:
        model (RoleModel): Role tableから取得済みの永続model.

    Returns:
        Role: permissionsをPrivilegesへ変換したdomain Role.

    Notes:
        positionとnameは永続値を変更せずに転記する.
    """
    return Role(
        id=model.id,
        name=model.name,
        permissions=Privileges(model.permissions),
        position=model.position,
    )


def channel_to_domain(model: ChannelModel) -> Channel:
    """永続化されたChannel modelをdomain Channelへ変換する.

    Args:
        model (ChannelModel): Channel tableから取得済みの永続model.

    Returns:
        Channel: channel_typeをChannelTypeへ変換したdomain Channel.

    Raises:
        ValueError: model.channel_typeがChannelTypeの既知値でない場合.

    Notes:
        rate limitとtimestampを含む永続fieldを変更せずに転記する.
    """
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
    """永続化されたchannel role overrideをdomain valueへ変換する.

    Args:
        model (ChannelRoleOverrideModel): ChannelとRoleの関連tableから取得済みの永続model.

    Returns:
        ChannelRoleOverride: channel,Role,read/write permissionを転記したdomain value.

    Notes:
        permissionの解決やdefault overrideの補完は行わない.
    """
    return ChannelRoleOverride(
        channel_id=model.channel_id,
        role_id=model.role_id,
        can_read=model.can_read,
        can_write=model.can_write,
    )


def score_to_domain(model: ScoreModel) -> Score:
    """永続化されたScore modelをdomain Scoreへ変換する.

    Args:
        model (ScoreModel): Score tableから取得済みの永続model.

    Returns:
        Score: enum値とmods bitmaskをdomain valueへ変換したScore.

    Raises:
        ValueError: 永続enum値を対応するdomain enumへ変換できない場合,またはmods bitmaskが
            永続化表現として無効な場合.

    Notes:
        NULL可能なsubmission fieldはNoneを維持し,replay dataはこの変換に含めない.
    """
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
    """永続化されたBlob modelをdomain Blobへ変換する.

    Args:
        model (BlobModel): Blob tableから取得済みの永続model.

    Returns:
        Blob: storage backend kindをdomain enumへ変換したBlob metadata.

    Raises:
        ValueError: model.storage_backendがBlobStorageBackendKindの既知値でない場合.

    Notes:
        blob payloadは読み込まず,metadataだけを転記する.
    """
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
    """永続化されたBeatmapset modelを所属Beatmapとともにdomain valueへ変換する.

    Args:
        model (BeatmapSetModel): Beatmapset tableから取得済みの永続model.
        beatmaps (tuple[Beatmap, ...]): 呼び出し側が取得済みの所属domain Beatmap.

    Returns:
        BeatmapSet: statusとmetadata sourceをdomain enumへ変換したBeatmapset.

    Raises:
        ValueError: official statusまたはmetadata sourceが対応するdomain enumの既知値でない場合.

    Notes:
        beatmapsの内容と順序は変更せずにそのまま保持する.
    """
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
        official_submitted_at=model.official_submitted_at,
        official_ranked_at=model.official_ranked_at,
        official_last_updated_at=model.official_last_updated_at,
        source_text=model.source_text,
        tags=model.tags,
    )


def beatmap_to_domain(
    model: BeatmapModel, attachment_model: BeatmapFileAttachmentModel | None
) -> Beatmap:
    """永続化されたBeatmap modelと現在attachmentをdomain Beatmapへ変換する.

    Args:
        model (BeatmapModel): Beatmap tableから取得済みの永続model.
        attachment_model (BeatmapFileAttachmentModel | None): 現在のfile attachment model.
            未取得時はNone.

    Returns:
        Beatmap: enum,numeric metadata,file stateをdomain valueへ変換したBeatmap.

    Raises:
        ValueError: Beatmap modelまたはattachment modelのenum値が対応するdomain enumの既知値で
            ない場合.

    Notes:
        checksum_md5がNoneの場合は空文字列とし,attachmentの有無だけでfile stateを決定する.
    """
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
    """永続化されたBeatmap file attachmentをdomain valueへ変換する.

    Args:
        model (BeatmapFileAttachmentModel): Beatmap file attachment tableから取得済みの永続model.

    Returns:
        BeatmapFileAttachment: sourceをBeatmapFileSourceへ変換したfile attachment value.

    Raises:
        ValueError: model.sourceがBeatmapFileSourceの既知値でない場合.

    Notes:
        fileの内容やblob objectは読み込まず,attachment metadataだけを転記する.
    """
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
    """永続化されたBeatmap fetch stateをdomain fetch recordへ変換する.

    Args:
        model (BeatmapFetchStateModel): Beatmap fetch state tableから取得済みの永続model.

    Returns:
        BeatmapFetchRecord: target kindとstatusをdomain enumへ変換した取得record.

    Raises:
        ValueError: model.target_typeまたはmodel.statusが対応するdomain enumの既知値でない場合.

    Notes:
        attempt count,error,timestampは永続値を変更せずに転記する.
    """
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
    """永続化されたverification flagをdomain enumへ変換する.

    Args:
        is_verified (bool): source metadataが検証済みかを示す永続flag.

    Returns:
        BeatmapSourceVerification: TrueならVERIFIED. FalseならUNVERIFIED.
    """
    return (
        BeatmapSourceVerification.VERIFIED if is_verified else BeatmapSourceVerification.UNVERIFIED
    )


def decimal_or_none(value: float | None) -> Decimal | None:
    """floatまたはNoneを精度を保つDecimal valueへ変換する.

    Args:
        value (float | None): 永続層から取得したnumeric value. 値がない場合はNone.

    Returns:
        Decimal | None: floatの文字列表現から生成したDecimal. 入力がNoneの場合はNone.

    Notes:
        Decimal(value)ではなくDecimal(str(value))を使い,binary floatの直接変換を避ける.
    """
    if value is None:
        return None
    return Decimal(str(value))
