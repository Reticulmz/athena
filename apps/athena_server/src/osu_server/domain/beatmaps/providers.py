"""Beatmap metadata/file provider contractとsnapshotを定義するmodule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from osu_server.domain.beatmaps._validation import validate_md5

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps.states import (
        BeatmapFileSource,
        BeatmapMetadataSource,
        BeatmapMode,
        BeatmapRankStatus,
        BeatmapSourceVerification,
        LocalBeatmapStatus,
    )


@dataclass(slots=True, frozen=True)
class BeatmapSnapshot:
    """Providerから取り込んだ単一beatmapのsnapshotを表す.

    Attributes:
        beatmap_id (int): providerが示したbeatmap ID.
        beatmapset_id (int): providerが示した所属beatmapset ID.
        checksum_md5 (str): beatmap内容を識別するMD5 checksum.
        mode (BeatmapMode): beatmapのgame mode.
        version (str): difficulty名.
        official_status (BeatmapRankStatus): providerが示した公式公開status.
        official_status_source (BeatmapMetadataSource): 公式statusを得たsource.
        official_status_verified (BeatmapSourceVerification): 公式statusの検証状態.
        local_status_override (LocalBeatmapStatus | None): operatorによるローカルstatus上書き.
            未設定時はNone.
        total_length (int | None): breakを含む総演奏時間. 不明な場合はNone.
        hit_length (int | None): noteを叩く演奏時間. 不明な場合はNone.
        max_combo (int | None): 最大combo数. 不明な場合はNone.
        bpm (float | None): BPM. 不明な場合はNone.
        cs (float | None): circle size. 不明な場合はNone.
        od (float | None): overall difficulty. 不明な場合はNone.
        ar (float | None): approach rate. 不明な場合はNone.
        hp (float | None): health drain. 不明な場合はNone.
        difficulty_rating (float | None): difficulty rating. 不明な場合はNone.
        last_fetched_at (datetime | None): providerから取得した日時. 未取得時はNone.
        next_refresh_at (datetime | None): provider metadataを再取得する予定日時. 未設定時はNone.
        official_last_updated_at (datetime | None): providerが示す公式更新日時. 不明な場合はNone.

    Notes:
        checksum_md5は32文字の小文字16進数MD5である.
    """

    beatmap_id: int
    beatmapset_id: int
    checksum_md5: str
    mode: BeatmapMode
    version: str
    official_status: BeatmapRankStatus
    official_status_source: BeatmapMetadataSource
    official_status_verified: BeatmapSourceVerification
    local_status_override: LocalBeatmapStatus | None = None
    total_length: int | None = None
    hit_length: int | None = None
    max_combo: int | None = None
    bpm: float | None = None
    cs: float | None = None
    od: float | None = None
    ar: float | None = None
    hp: float | None = None
    difficulty_rating: float | None = None
    last_fetched_at: datetime | None = None
    next_refresh_at: datetime | None = None
    official_last_updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """SnapshotのMD5 checksumが有効か検証する.

        Returns:
            None: checksum_md5を検証して完了する.

        Raises:
            ValueError: checksum_md5が32文字の小文字16進数でない場合.
        """
        validate_md5(self.checksum_md5)


@dataclass(slots=True, frozen=True)
class BeatmapsetSnapshot:
    """Providerから取り込んだbeatmapset全体のsnapshotを表す.

    Attributes:
        beatmapset_id (int): providerが示したbeatmapset ID.
        artist (str): artist名.
        title (str): 曲名.
        creator (str): beatmapset作成者名.
        source (BeatmapMetadataSource): snapshot全体を取得したsource.
        verified (BeatmapSourceVerification): snapshot全体の検証状態.
        official_status (BeatmapRankStatus): providerが示した公式公開status.
        official_status_source (BeatmapMetadataSource): 公式statusを得たsource.
        official_status_verified (BeatmapSourceVerification): 公式statusの検証状態.
        beatmaps (tuple[BeatmapSnapshot, ...]): 所属beatmap snapshotの不変列.
        artist_unicode (str | None): Unicode表記のartist名. 未提供時はNone.
        title_unicode (str | None): Unicode表記の曲名. 未提供時はNone.
        last_fetched_at (datetime | None): providerから取得した日時. 未取得時はNone.
        next_refresh_at (datetime | None): 次回metadata refresh予定日時. 未設定時はNone.
        official_submitted_at (datetime | None): providerが示す公式投稿日時. 不明な場合はNone.
        official_ranked_at (datetime | None): providerが示す公式ranked日時. 不明な場合はNone.
        official_last_updated_at (datetime | None): providerが示す公式更新日時. 不明な場合はNone.
        source_text (str): 曲の出典としてproviderが返した検索対象文字列.
        tags (str): providerが返したtag検索文字列.
    """

    beatmapset_id: int
    artist: str
    title: str
    creator: str
    source: BeatmapMetadataSource
    verified: BeatmapSourceVerification
    official_status: BeatmapRankStatus
    official_status_source: BeatmapMetadataSource
    official_status_verified: BeatmapSourceVerification
    beatmaps: tuple[BeatmapSnapshot, ...]
    artist_unicode: str | None = None
    title_unicode: str | None = None
    last_fetched_at: datetime | None = None
    next_refresh_at: datetime | None = None
    official_submitted_at: datetime | None = None
    official_ranked_at: datetime | None = None
    official_last_updated_at: datetime | None = None
    source_text: str = ""
    tags: str = ""


@runtime_checkable
class BeatmapMetadataProvider(Protocol):
    """Beatmap metadataを検索するproviderのstructural contractを表す.

    Notes:
        実装は各lookupで一致するbeatmapset全体のsnapshotを返し,見つからない場合はNoneを返す.
    """

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        """Beatmap IDで所属beatmapset metadataを検索する.

        Args:
            beatmap_id (int): 検索するbeatmap ID.

        Returns:
            BeatmapsetSnapshot | None: 一致するbeatmapset snapshot. 見つからない場合はNone.

        Raises:
            BeatmapSourceError: metadata sourceが利用不能か,source responseを検証できない場合.
        """
        ...

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        """Beatmapset IDでmetadataを検索する.

        Args:
            beatmapset_id (int): 検索するbeatmapset ID.

        Returns:
            BeatmapsetSnapshot | None: 一致するbeatmapset snapshot. 見つからない場合はNone.

        Raises:
            BeatmapSourceError: metadata sourceが利用不能か,source responseを検証できない場合.
        """
        ...

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        """MD5 checksumで所属beatmapset metadataを検索する.

        Args:
            checksum_md5 (str): 検索するbeatmapのMD5 checksum.

        Returns:
            BeatmapsetSnapshot | None: 一致するbeatmapset snapshot. 見つからない場合はNone.

        Raises:
            BeatmapSourceError: metadata sourceが利用不能か,source responseを検証できない場合.
        """
        ...


@dataclass(slots=True, frozen=True)
class OsuFileFetchResult:
    """Osu file providerが返す取得済みfileを表す.

    Attributes:
        beatmap_id (int): 取得したosu fileのbeatmap ID.
        body (bytes): 取得したosu fileのbody bytes.
        source (BeatmapFileSource): fileを取得したsource.
        original_filename (str | None): sourceが提示した元file名. 不明な場合はNone.
    """

    beatmap_id: int
    body: bytes
    source: BeatmapFileSource
    original_filename: str | None


@runtime_checkable
class BeatmapFileProvider(Protocol):
    """Osu fileを取得するproviderのstructural contractを表す."""

    async def fetch_osu_file(self, beatmap_id: int) -> OsuFileFetchResult:
        """Beatmap IDに対応するosu fileを取得する.

        Args:
            beatmap_id (int): 取得するosu fileのbeatmap ID.

        Returns:
            OsuFileFetchResult: body bytesと取得sourceを含むfile取得結果.

        Raises:
            BeatmapSourceError: すべてのfile sourceが利用不能か,取得結果を検証できない場合.
        """
        ...
