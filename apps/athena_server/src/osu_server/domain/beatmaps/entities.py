"""Beatmap difficultyとbeatmapsetのcore entityを定義するmodule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps._validation import (
    validate_beatmapset_child_ownership,
    validate_local_override,
    validate_md5,
)
from osu_server.domain.beatmaps.states import (
    BeatmapFetchState,
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(slots=True, frozen=True)
class BeatmapFileAttachment:
    """Beatmapに紐づく取得済みosu file blobを表す.

    Attributes:
        beatmap_id (int): attachmentを所有するBeatmap ID.
        blob_id (int): osu file本体を保持するBlob ID.
        checksum_md5 (str): osu file内容のMD5 checksum.
        source (BeatmapFileSource): fileを取得したsource.
        original_filename (str | None): sourceが提示した元file名.
        fetched_at (datetime): fileを取得した日時.
        verified_at (datetime | None): checksumを検証した日時.
        id (int | None): 永続化前はNoneとなるattachment ID.

    Notes:
        checksum_md5は32文字の小文字16進数MD5で,設定済みidは正の値に限る.
    """

    beatmap_id: int
    blob_id: int
    checksum_md5: str
    source: BeatmapFileSource
    original_filename: str | None
    fetched_at: datetime
    verified_at: datetime | None
    id: int | None = None

    def __post_init__(self) -> None:
        """Attachment IDとMD5 checksumの不変条件を検証する.

        Returns:
            None: checksumと任意の永続IDを検証して完了する.

        Raises:
            ValueError: checksum_md5が小文字16進数MD5でないか,idが正の値でない場合.
        """
        validate_md5(self.checksum_md5)
        if self.id is not None and self.id <= 0:
            msg = "id must be positive"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
class Beatmap:
    """単一beatmap difficultyと取得状態を表す.

    Attributes:
        id (int): 永続beatmap ID.
        beatmapset_id (int): 所属するbeatmapset ID.
        checksum_md5 (str): beatmap内容を識別するMD5 checksum.
        mode (BeatmapMode): beatmapのgame mode.
        version (str): difficulty名.
        total_length (int | None): breakを含む総演奏時間. 不明な場合はNone.
        hit_length (int | None): noteを叩く演奏時間. 不明な場合はNone.
        max_combo (int | None): 最大combo数. 不明な場合はNone.
        bpm (float | None): BPM. 不明な場合はNone.
        cs (float | None): circle size. 不明な場合はNone.
        od (float | None): overall difficulty. 不明な場合はNone.
        ar (float | None): approach rate. 不明な場合はNone.
        hp (float | None): health drain. 不明な場合はNone.
        difficulty_rating (float | None): difficulty rating. 不明な場合はNone.
        official_status (BeatmapRankStatus): providerが示した公式公開status.
        official_status_source (BeatmapMetadataSource): 公式statusを得たsource.
        official_status_verified (BeatmapSourceVerification): 公式statusの検証状態.
        local_status_override (LocalBeatmapStatus | None): operatorによるローカルstatus上書き.
            未設定時はNone.
        metadata_fetch_state (BeatmapFetchState): metadata取得の状態.
        file_state (BeatmapFileState): osu file取得の状態.
        file_attachment (BeatmapFileAttachment | None): 取得済みosu fileへのattachment.
            存在しない場合はNone.
        last_fetched_at (datetime | None): metadataを最後に取得した日時. 未取得時はNone.
        next_refresh_at (datetime | None): 次回refresh予定日時. 未設定時はNone.
        official_last_updated_at (datetime | None): providerが示す公式更新日時. 不明な場合はNone.
        local_status_override_changed_at (datetime | None): ローカル上書きを変更した日時.
            未設定時はNone.

    Notes:
        checksum_md5は小文字16進数MD5である. APPROVEDはlocal_status_overrideに使えない.
    """

    id: int
    beatmapset_id: int
    checksum_md5: str
    mode: BeatmapMode
    version: str
    total_length: int | None
    hit_length: int | None
    max_combo: int | None
    bpm: float | None
    cs: float | None
    od: float | None
    ar: float | None
    hp: float | None
    difficulty_rating: float | None
    official_status: BeatmapRankStatus
    official_status_source: BeatmapMetadataSource
    official_status_verified: BeatmapSourceVerification
    local_status_override: LocalBeatmapStatus | None
    metadata_fetch_state: BeatmapFetchState
    file_state: BeatmapFileState
    file_attachment: BeatmapFileAttachment | None
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None
    official_last_updated_at: datetime | None = None
    local_status_override_changed_at: datetime | None = None

    def __post_init__(self) -> None:
        """Checksum,ローカルstatus上書き,attachment所有IDを検証する.

        Returns:
            None: checksum,local_status_override,attachment所有IDを検証して完了する.

        Raises:
            TypeError: local_status_overrideがLocalBeatmapStatusまたはNoneでない場合.
            ValueError: checksum_md5が無効,APPROVEDをローカル上書きに指定,または
                file_attachmentの所有IDが一致しない場合.
        """
        validate_md5(self.checksum_md5)
        validate_local_override(self.local_status_override)
        if self.file_attachment is not None and self.file_attachment.beatmap_id != self.id:
            msg = "file_attachment.beatmap_id must match Beatmap.id"
            raise ValueError(msg)

    @property
    def effective_status(self) -> BeatmapRankStatus:
        """ローカル上書きを反映した採用statusを返す.

        Returns:
            BeatmapRankStatus: local_status_overrideがあればそのstatus. なければofficial_status.
        """
        if self.local_status_override is None:
            return self.official_status
        return BeatmapRankStatus(self.local_status_override.value)


@dataclass(slots=True, frozen=True)
class BeatmapSet:
    """同じbeatmapsetに属するdifficulty群とset metadataを表す.

    Attributes:
        id (int): 永続beatmapset ID.
        artist (str): artist名.
        title (str): 曲名.
        creator (str): beatmapset作成者名.
        artist_unicode (str | None): Unicode表記のartist名. 未提供時はNone.
        title_unicode (str | None): Unicode表記の曲名. 未提供時はNone.
        official_status (BeatmapRankStatus): beatmapsetの公式公開status.
        official_status_source (BeatmapMetadataSource): 公式statusを得たsource.
        official_status_verified (BeatmapSourceVerification): 公式statusの検証状態.
        beatmaps (tuple[Beatmap, ...]): 所属するbeatmap difficultyの不変列.
        last_fetched_at (datetime | None): metadataを最後に取得した日時. 未取得時はNone.
        next_refresh_at (datetime | None): 次回refresh予定日時. 未設定時はNone.
        official_submitted_at (datetime | None): providerが示す公式投稿日時. 不明な場合はNone.
        official_ranked_at (datetime | None): providerが示す公式ranked日時. 不明な場合はNone.
        official_last_updated_at (datetime | None): providerが示す公式更新日時. 不明な場合はNone.
        source_text (str): 曲の出典としてproviderが返した検索対象文字列.
        tags (str): providerが返したtag検索文字列.
    """

    id: int
    artist: str
    title: str
    creator: str
    artist_unicode: str | None
    title_unicode: str | None
    official_status: BeatmapRankStatus
    official_status_source: BeatmapMetadataSource
    official_status_verified: BeatmapSourceVerification
    beatmaps: tuple[Beatmap, ...]
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None
    official_submitted_at: datetime | None = None
    official_ranked_at: datetime | None = None
    official_last_updated_at: datetime | None = None
    source_text: str = ""
    tags: str = ""

    def __post_init__(self) -> None:
        """全difficultyがこのbeatmapsetに属することを検証する.

        Returns:
            None: child beatmapの所有IDを検証して完了する.

        Raises:
            ValueError: child beatmapのbeatmapset IDがこのset IDと一致しない場合.
        """
        validate_beatmapset_child_ownership(
            tuple(beatmap.beatmapset_id for beatmap in self.beatmaps),
            self.id,
            mismatch_message="beatmap.beatmapset_id must match BeatmapSet.id",
        )
