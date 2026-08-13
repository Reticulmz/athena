"""Beatmapの公開状態,鮮度,取得対象を表すdomain modelを定義するmodule.

公式rank status,operatorのローカル上書き,metadata/fileの鮮度,
leaderboard eligibilityを同じ語彙として扱う.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from osu_server.shared.checksums import MD5_HEX_LENGTH, is_lowercase_md5_hexdigest

if TYPE_CHECKING:
    from datetime import datetime, timedelta


class BeatmapRankStatus(Enum):
    """外部metadataが示す公式beatmap公開状態を表す閉集合.

    Attributes:
        RANKED (str): rankedとして公開されていることを示す値.
        APPROVED (str): approvedとして公開されていることを示す値.
        LOVED (str): lovedとして公開されていることを示す値.
        QUALIFIED (str): qualifiedとして審査中であることを示す値.
        PENDING (str): pendingであることを示す値.
        WIP (str): work in progressであることを示す値.
        GRAVEYARD (str): graveyardにあることを示す値.
        NOT_SUBMITTED (str): 公開statusが未提出であることを示す値.
        UNKNOWN (str): provider値を公式statusへ分類できないことを示す値.
    """

    RANKED = "ranked"
    APPROVED = "approved"
    LOVED = "loved"
    QUALIFIED = "qualified"
    PENDING = "pending"
    WIP = "wip"
    GRAVEYARD = "graveyard"
    NOT_SUBMITTED = "not_submitted"
    UNKNOWN = "unknown"


class BeatmapMode(Enum):
    """Beatmapのgame modeを表す閉集合.

    Attributes:
        OSU (str): osu!standard modeの永続化値.
        TAIKO (str): osu!taiko modeの永続化値.
        FRUITS (str): osu!catch modeの永続化値.
        MANIA (str): osu!mania modeの永続化値.
        UNKNOWN (str): provider値をmodeへ確定できない場合の永続化値.

    Notes:
        Domain内ではEnum memberを使い,wire/DB境界だけで文字列値へ変換する.
    """

    OSU = "osu"
    TAIKO = "taiko"
    FRUITS = "fruits"
    MANIA = "mania"
    UNKNOWN = "unknown"


class LocalBeatmapStatus(Enum):
    """Athena operatorが上書きできるローカルbeatmap公開状態を表す閉集合.

    Attributes:
        RANKED (str): rankedとして扱うことを示す値.
        LOVED (str): lovedとして扱うことを示す値.
        QUALIFIED (str): qualifiedとして扱うことを示す値.
        PENDING (str): pendingとして扱うことを示す値.
        WIP (str): work in progressとして扱うことを示す値.
        GRAVEYARD (str): graveyardとして扱うことを示す値.
        NOT_SUBMITTED (str): 未提出として扱うことを示す値.
        UNKNOWN (str): statusを確定できないとして扱うことを示す値.

    Notes:
        APPROVEDは公式status専用のため,ローカル上書きには含めない.
    """

    RANKED = "ranked"
    LOVED = "loved"
    QUALIFIED = "qualified"
    PENDING = "pending"
    WIP = "wip"
    GRAVEYARD = "graveyard"
    NOT_SUBMITTED = "not_submitted"
    UNKNOWN = "unknown"


class BeatmapMetadataSource(Enum):
    """Beatmap metadataの取得元を表す閉集合.

    Attributes:
        OFFICIAL (str): 現行公式sourceから取得したことを示す値.
        LEGACY_OFFICIAL (str): legacy公式sourceから取得したことを示す値.
        MIRROR (str): mirror sourceから取得したことを示す値.
    """

    OFFICIAL = "official"
    LEGACY_OFFICIAL = "legacy_official"
    MIRROR = "mirror"


class BeatmapSourceVerification(Enum):
    """Metadata sourceを公式情報として信頼できるかを表す閉集合.

    Attributes:
        VERIFIED (str): 公式情報として検証済みであることを示す値.
        UNVERIFIED (str): 公式情報として検証できていないことを示す値.
    """

    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class BeatmapFetchState(Enum):
    """Beatmap metadata fetchの状態を表す閉集合.

    Attributes:
        FRESH (str): metadataが現在のrefresh期限内であることを示す値.
        STALE (str): metadataのrefresh期限を過ぎたことを示す値.
        PENDING_FETCH (str): metadata fetchを実行中または待機中であることを示す値.
        FAILED (str): 直近のmetadata fetchが失敗したことを示す値.
    """

    FRESH = "fresh"
    STALE = "stale"
    PENDING_FETCH = "pending_fetch"
    FAILED = "failed"


class BeatmapFileState(Enum):
    """osu file attachmentの取得状態を表す閉集合.

    Attributes:
        AVAILABLE (str): osu file attachmentを利用できることを示す値.
        PENDING_FETCH (str): osu file fetchを実行中または待機中であることを示す値.
        MISSING (str): osu file attachmentが存在しないことを示す値.
        FAILED (str): 直近のosu file fetchが失敗したことを示す値.
    """

    AVAILABLE = "available"
    PENDING_FETCH = "pending_fetch"
    MISSING = "missing"
    FAILED = "failed"


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
        _validate_md5(self.checksum_md5)
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
        """MD5 checksumとローカルstatus上書きの不変条件を検証する.

        Returns:
            None: checksumとlocal_status_overrideを検証して完了する.

        Raises:
            TypeError: local_status_overrideがLocalBeatmapStatusまたはNoneでない場合.
            ValueError: checksum_md5が無効か,APPROVEDをローカル上書きに指定した場合.
        """
        _validate_md5(self.checksum_md5)
        _validate_local_override(self.local_status_override)

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
    source_text: str = ""
    tags: str = ""


def _validate_md5(checksum_md5: str) -> None:
    """MD5 checksumが小文字16進数の固定長値か検証する.

    Args:
        checksum_md5 (str): 検証するMD5 checksum.

    Returns:
        None: checksum_md5が有効であることを確認して完了する.

    Raises:
        ValueError: checksum_md5が32文字の小文字16進数でない場合.
    """
    if not is_lowercase_md5_hexdigest(checksum_md5):
        msg = f"checksum_md5 must be a {MD5_HEX_LENGTH}-character lowercase hexadecimal string"
        raise ValueError(msg)


def _validate_local_override(status: object) -> None:
    """ローカルstatus上書きに許可された値だけを受け入れる.

    Args:
        status (object): 検証するローカルstatus上書き値.

    Returns:
        None: statusがLocalBeatmapStatusまたはNoneであることを確認して完了する.

    Raises:
        TypeError: statusがLocalBeatmapStatusまたはNoneでない場合.
        ValueError: statusが公式status専用のAPPROVEDである場合.
    """
    if status is None:
        return
    if status is BeatmapRankStatus.APPROVED:
        msg = "Approved cannot be used as a local override"
        raise ValueError(msg)
    if not isinstance(status, LocalBeatmapStatus):
        msg = "local_status_override must be a LocalBeatmapStatus or None"
        raise TypeError(msg)


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

_EXTERNAL_STATUS_MAP: dict[str, BeatmapRankStatus] = {
    "ranked": BeatmapRankStatus.RANKED,
    "approved": BeatmapRankStatus.APPROVED,
    "loved": BeatmapRankStatus.LOVED,
    "qualified": BeatmapRankStatus.QUALIFIED,
    "pending": BeatmapRankStatus.PENDING,
    "wip": BeatmapRankStatus.WIP,
    "graveyard": BeatmapRankStatus.GRAVEYARD,
}


def map_external_status(status: str) -> BeatmapRankStatus:
    """外部providerのstatus文字列をcanonical statusへ変換する.

    Args:
        status (str): providerから受け取ったstatus文字列.

    Returns:
        BeatmapRankStatus: 前後空白を除去して小文字化したstatusに対応する値. 未知の値はUNKNOWN.
    """
    normalized = status.strip().lower()
    return _EXTERNAL_STATUS_MAP.get(normalized, BeatmapRankStatus.UNKNOWN)


_STABLE_STATUSES: frozenset[BeatmapRankStatus] = frozenset(
    {BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED, BeatmapRankStatus.LOVED}
)
_PENDING_LIKE_STATUSES: frozenset[BeatmapRankStatus] = frozenset(
    {BeatmapRankStatus.QUALIFIED, BeatmapRankStatus.PENDING, BeatmapRankStatus.WIP}
)


def _is_mirror_sourced(beatmap: Beatmap) -> bool:
    """Beatmap metadataがmirror由来かを返す.

    Args:
        beatmap (Beatmap): 取得元を確認するbeatmap.

    Returns:
        bool: official_status_sourceがMIRRORの場合はTrue.
    """
    return beatmap.official_status_source is BeatmapMetadataSource.MIRROR


@dataclass(slots=True, frozen=True)
class BeatmapFreshnessDecision:
    """Metadata freshness policyの判定結果を表す.

    Attributes:
        is_stale (bool): metadataがrefresh期限を過ぎたか,または公式sourceを利用できる
            mirror由来recordであるか.
        should_refresh (bool): metadata fetchを要求すべきか.
        requests_official_refresh (bool): mirror由来recordに公式sourceでの再取得を要求するか.
        next_refresh_at (datetime | None): 判定に使用した次回refresh日時. 未確定時はNone.
        reason (str | None): refresh判断の理由code. 通常のfresh状態ではNoneだが,
            PENDING_FETCHではpending_fetchを返す.
    """

    is_stale: bool
    should_refresh: bool
    requests_official_refresh: bool
    next_refresh_at: datetime | None
    reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapFreshnessPolicy:
    """Beatmap metadataを再取得すべきか判定するpolicyを表す.

    Attributes:
        ranked_refresh_interval (timedelta): ranked,approved,lovedのrefresh間隔.
        pending_refresh_interval (timedelta): qualified,pending,WIPなどのrefresh間隔.
        graveyard_refresh_interval (timedelta): graveyardのrefresh間隔.
        mirror_refresh_interval (timedelta): mirror由来metadataのrefresh間隔.
    """

    ranked_refresh_interval: timedelta
    pending_refresh_interval: timedelta
    graveyard_refresh_interval: timedelta
    mirror_refresh_interval: timedelta

    def evaluate(
        self,
        beatmap: Beatmap,
        *,
        now: datetime,
        official_sources_available: bool = False,
        force_refresh: bool = False,
    ) -> BeatmapFreshnessDecision:
        """現在時刻と取得元からstale/refresh判定を返す.

        Args:
            beatmap (Beatmap): freshnessを判定するbeatmap.
            now (datetime): 判定に使う現在時刻.
            official_sources_available (bool): 公式metadata sourceを利用できるか.
            force_refresh (bool): freshでもmetadata fetchを強制するか.

        Returns:
            BeatmapFreshnessDecision: stale状態,refresh要否,公式source再取得要否を含む判定結果.

        Notes:
            force_refreshがFalseのPENDING_FETCHではshould_refreshをFalseにし,
            reasonとしてpending_fetchを返す. 公式sourceが利用できるmirror由来recordは
            次回予定日時に関わらず公式再取得を要求する.
        """
        next_refresh_at = self._effective_next_refresh_at(beatmap)
        is_stale = next_refresh_at is not None and next_refresh_at <= now

        if force_refresh:
            return BeatmapFreshnessDecision(
                is_stale=is_stale,
                should_refresh=True,
                requests_official_refresh=official_sources_available
                and _is_mirror_sourced(beatmap),
                next_refresh_at=next_refresh_at,
                reason="force_refresh",
            )

        if beatmap.metadata_fetch_state is BeatmapFetchState.PENDING_FETCH:
            return BeatmapFreshnessDecision(
                is_stale=is_stale,
                should_refresh=False,
                requests_official_refresh=False,
                next_refresh_at=next_refresh_at,
                reason="pending_fetch",
            )

        if beatmap.metadata_fetch_state is BeatmapFetchState.FAILED:
            return BeatmapFreshnessDecision(
                is_stale=is_stale,
                should_refresh=True,
                requests_official_refresh=official_sources_available
                and _is_mirror_sourced(beatmap),
                next_refresh_at=next_refresh_at,
                reason="failed_fetch",
            )

        if official_sources_available and _is_mirror_sourced(beatmap):
            return BeatmapFreshnessDecision(
                is_stale=True,
                should_refresh=True,
                requests_official_refresh=True,
                next_refresh_at=next_refresh_at,
                reason="mirror_official_refresh_due",
            )

        if is_stale:
            return BeatmapFreshnessDecision(
                is_stale=True,
                should_refresh=True,
                requests_official_refresh=official_sources_available
                and _is_mirror_sourced(beatmap),
                next_refresh_at=next_refresh_at,
                reason="stale",
            )

        return BeatmapFreshnessDecision(
            is_stale=False,
            should_refresh=False,
            requests_official_refresh=False,
            next_refresh_at=next_refresh_at,
            reason=None,
        )

    def _effective_next_refresh_at(self, beatmap: Beatmap) -> datetime | None:
        """保存済みまたはpolicy導出の次回refresh日時を選ぶ.

        Args:
            beatmap (Beatmap): refresh日時を取得するbeatmap.

        Returns:
            datetime | None: 有効な保存済みnext_refresh_at. 不在またはlast_fetched_at以下なら
                policy導出値.
        """
        if beatmap.last_fetched_at is None:
            return beatmap.next_refresh_at
        if beatmap.next_refresh_at is None:
            return self._derive_next_refresh_at(beatmap)
        if beatmap.next_refresh_at <= beatmap.last_fetched_at:
            return self._derive_next_refresh_at(beatmap)
        return beatmap.next_refresh_at

    def _derive_next_refresh_at(self, beatmap: Beatmap) -> datetime | None:
        """取得時刻,source,採用statusから次回refresh日時を導出する.

        Args:
            beatmap (Beatmap): refresh日時を導出するbeatmap.

        Returns:
            datetime | None: last_fetched_atに適切なintervalを加えた日時. 未取得ならNone.

        Notes:
            mirror由来recordはstatusにかかわらずmirror_refresh_intervalを使用する.
        """
        if beatmap.last_fetched_at is None:
            return None

        if _is_mirror_sourced(beatmap):
            return beatmap.last_fetched_at + self.mirror_refresh_interval

        status = beatmap.effective_status
        if status in _STABLE_STATUSES:
            return beatmap.last_fetched_at + self.ranked_refresh_interval
        if status in _PENDING_LIKE_STATUSES:
            return beatmap.last_fetched_at + self.pending_refresh_interval
        if status is BeatmapRankStatus.GRAVEYARD:
            return beatmap.last_fetched_at + self.graveyard_refresh_interval
        return beatmap.last_fetched_at + self.pending_refresh_interval


@dataclass(slots=True, frozen=True)
class BeatmapEligibility:
    """Score submissionとleaderboard更新で使うbeatmap適格性を表す.

    Attributes:
        accepts_scores (bool): score submissionを受け付けるか.
        has_leaderboard (bool): leaderboardを持つか.
        awards_ranked_pp (bool): ranked PPを付与するか.
        awards_loved_pp (bool): loved PPを付与するか.
        requires_osu_file_for_pp (bool): PP計算にosu fileを必要とするか.
        is_officially_verified (bool): metadataが公式情報として検証済みか.
        is_mirror_derived (bool): metadataがmirror由来か.
        accepts_failed_scores (bool): failed scoreを受け付けるか.
        failed_scores_have_leaderboard (bool): failed scoreをleaderboardへ反映するか.
        failed_scores_update_best_score (bool): failed scoreでbest scoreを更新するか.
        failed_scores_award_ranked_pp (bool): failed scoreにranked PPを付与するか.
        failed_scores_award_loved_pp (bool): failed scoreにloved PPを付与するか.
        denial_reason (str | None): scoreを受け付けない理由. 受け付ける場合はNone.
    """

    accepts_scores: bool
    has_leaderboard: bool
    awards_ranked_pp: bool
    awards_loved_pp: bool
    requires_osu_file_for_pp: bool
    is_officially_verified: bool
    is_mirror_derived: bool
    accepts_failed_scores: bool
    failed_scores_have_leaderboard: bool
    failed_scores_update_best_score: bool
    failed_scores_award_ranked_pp: bool
    failed_scores_award_loved_pp: bool
    denial_reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapResolveOptions:
    """Beatmap resolutionの挙動を制御するoptionを表す.

    Attributes:
        require_osu_file (bool): resultにosu fileが存在することを必須にするか.
        wait_timeout_seconds (float): 進行中fetchの完了を待つ最大秒数.
        force_refresh (bool): cached metadataにかかわらずrefreshを要求するか.
    """

    require_osu_file: bool = False
    wait_timeout_seconds: float = 0.0
    force_refresh: bool = False


@dataclass(slots=True, frozen=True)
class BeatmapResolveResult:
    """単一beatmap resolutionの構造化された結果を表す.

    Attributes:
        beatmap (Beatmap | None): 解決したbeatmap. 解決不能時はNone.
        beatmapset (BeatmapSet | None): beatmapが属するset. 解決不能時はNone.
        eligibility (BeatmapEligibility | None): 解決したbeatmapの適格性. 解決不能時はNone.
        metadata_status (BeatmapFetchState): metadata fetchの状態.
        file_status (BeatmapFileState): osu file fetchの状態.
        source (BeatmapMetadataSource | None): 利用したmetadata source. 未確定時はNone.
        verified (bool): metadataが公式情報として検証済みか.
        last_fetched_at (datetime | None): metadataを最後に取得した日時. 未取得時はNone.
        next_refresh_at (datetime | None): 次回metadata refresh予定日時. 未設定時はNone.
        reason (str | None): 解決不能または保留の理由. 解決時はNone.
    """

    beatmap: Beatmap | None
    beatmapset: BeatmapSet | None
    eligibility: BeatmapEligibility | None
    metadata_status: BeatmapFetchState
    file_status: BeatmapFileState
    source: BeatmapMetadataSource | None
    verified: bool
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None
    reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapSetResolveResult:
    """Beatmapset resolutionの構造化された結果を表す.

    Attributes:
        beatmapset (BeatmapSet | None): 解決したbeatmapset. 解決不能時はNone.
        metadata_status (BeatmapFetchState): metadata fetchの状態.
        source (BeatmapMetadataSource | None): 利用したmetadata source. 未確定時はNone.
        verified (bool): metadataが公式情報として検証済みか.
        last_fetched_at (datetime | None): metadataを最後に取得した日時. 未取得時はNone.
        next_refresh_at (datetime | None): 次回metadata refresh予定日時. 未設定時はNone.
        reason (str | None): 解決不能または保留の理由. 解決時はNone.
    """

    beatmapset: BeatmapSet | None
    metadata_status: BeatmapFetchState
    source: BeatmapMetadataSource | None
    verified: bool
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None
    reason: str | None


class BeatmapFetchTargetKind(Enum):
    """Beatmap domainが所有するfetch target encodingを表す閉集合.

    Attributes:
        METADATA_BY_BEATMAP_ID (str): beatmap IDでmetadataを取得するtarget.
        METADATA_BY_BEATMAPSET_ID (str): beatmapset IDでmetadataを取得するtarget.
        METADATA_BY_CHECKSUM (str): MD5 checksumでmetadataを取得するtarget.
        FILE_BY_BEATMAP_ID (str): beatmap IDでosu fileを取得するtarget.
    """

    METADATA_BY_BEATMAP_ID = "metadata:beatmap"
    METADATA_BY_BEATMAPSET_ID = "metadata:beatmapset"
    METADATA_BY_CHECKSUM = "metadata:checksum"
    FILE_BY_BEATMAP_ID = "file:beatmap"


class BeatmapMetadataLookupKind(Enum):
    """Fetch targetから導出するmetadata provider lookup種別を表す閉集合.

    Attributes:
        BEATMAP_ID (str): beatmap IDによるlookupを示す値.
        BEATMAPSET_ID (str): beatmapset IDによるlookupを示す値.
        CHECKSUM (str): MD5 checksumによるlookupを示す値.
    """

    BEATMAP_ID = "beatmap_id"
    BEATMAPSET_ID = "beatmapset_id"
    CHECKSUM = "checksum"


@dataclass(slots=True, frozen=True)
class BeatmapMetadataLookupTarget:
    """Fetch targetが要求するprovider非依存metadata lookupを表す.

    Attributes:
        kind (BeatmapMetadataLookupKind): lookupに使う識別子の種別.
        value (str): providerへ渡す識別子の文字列表現.
    """

    kind: BeatmapMetadataLookupKind
    value: str

    def int_value(self) -> int:
        """Lookup値を正の整数識別子として返す.

        Returns:
            int: valueを変換した正の整数.

        Raises:
            ValueError: valueが整数へ変換できないか,0以下の場合.
        """
        value = int(self.value)
        if value <= 0:
            msg = f"lookup value must be positive: {self.value}"
            raise ValueError(msg)
        return value


@dataclass(slots=True, frozen=True)
class BeatmapFetchQueuePayload:
    """Worker queueへ渡すprimitive fetch payloadを表す.

    Attributes:
        target_type (str): queueで使うfetch target typeの文字列表現.
        target_key (str): target typeに対応するlookup key.
        force_refresh (bool): cached状態にかかわらずrefreshを要求するか.
    """

    target_type: str
    target_key: str
    force_refresh: bool = False


@dataclass(slots=True, frozen=True)
class BeatmapFetchTarget:
    """Fetch queue encodingを隠すbeatmap metadata/file取得対象を表す.

    Attributes:
        target_type (BeatmapFetchTargetKind): metadataまたはfile fetchのtarget type.
        target_key (str): target typeに対応する非空のlookup key.
        force_refresh (bool): cached状態にかかわらずrefreshを要求するか.

    Notes:
        target_keyの解釈はtarget_typeに依存する. file targetはmetadata lookupに使えない.
    """

    target_type: BeatmapFetchTargetKind
    target_key: str
    force_refresh: bool = field(default=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        """Target typeと非空lookup keyの不変条件を検証する.

        Returns:
            None: target_typeとtarget_keyを検証して完了する.

        Raises:
            ValueError: target_typeが未対応か,target_keyが空文字列の場合.
        """
        _ = self.kind
        if not self.target_key:
            raise ValueError("target_key must not be empty")

    @property
    def kind(self) -> BeatmapFetchTargetKind:
        """Target typeをtyped fetch target kindとして返す.

        Returns:
            BeatmapFetchTargetKind: target_typeに対応するenum member.

        Raises:
            ValueError: target_typeがBeatmapFetchTargetKindの値でない場合.
        """
        try:
            return BeatmapFetchTargetKind(self.target_type)
        except ValueError as exc:
            msg = f"unsupported beatmap fetch target type: {self.target_type}"
            raise ValueError(msg) from exc

    @property
    def is_file_fetch(self) -> bool:
        """このtargetをfile fetch workerが処理するか返す.

        Returns:
            bool: kindがFILE_BY_BEATMAP_IDの場合はTrue.

        Raises:
            ValueError: target_typeがBeatmapFetchTargetKindの値でない場合.
        """
        return self.kind is BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID

    def metadata_lookup_target(self) -> BeatmapMetadataLookupTarget:
        """このfetch targetが表すmetadata lookupを返す.

        Returns:
            BeatmapMetadataLookupTarget: metadata providerへ渡すlookup種別と値.

        Raises:
            ValueError: target_typeが未対応か,file fetch targetをmetadata lookupへ
                変換しようとした場合.
        """
        match self.kind:
            case BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID:
                return BeatmapMetadataLookupTarget(
                    kind=BeatmapMetadataLookupKind.BEATMAP_ID,
                    value=self.target_key,
                )
            case BeatmapFetchTargetKind.METADATA_BY_BEATMAPSET_ID:
                return BeatmapMetadataLookupTarget(
                    kind=BeatmapMetadataLookupKind.BEATMAPSET_ID,
                    value=self.target_key,
                )
            case BeatmapFetchTargetKind.METADATA_BY_CHECKSUM:
                return BeatmapMetadataLookupTarget(
                    kind=BeatmapMetadataLookupKind.CHECKSUM,
                    value=self.target_key,
                )
            case BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID:
                msg = "file fetch target cannot be used for metadata lookup"
                raise ValueError(msg)

    def file_beatmap_id(self) -> int:
        """File fetch targetが表すbeatmap IDを返す.

        Returns:
            int: target_keyを整数化したbeatmap ID.

        Raises:
            ValueError: target_typeがfile fetchでないか,target_keyを整数へ変換できない場合.
        """
        if self.kind is not BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID:
            msg = f"unsupported file fetch target type: {self.target_type}"
            raise ValueError(msg)
        return int(self.target_key)

    def queue_payload(self) -> BeatmapFetchQueuePayload:
        """Worker queueへ渡せるprimitive payloadを返す.

        Returns:
            BeatmapFetchQueuePayload: kindの文字列表現,target key,force refresh指定を持つpayload.

        Raises:
            ValueError: target_typeがBeatmapFetchTargetKindの値でない場合.
        """
        return BeatmapFetchQueuePayload(
            target_type=self.kind.value,
            target_key=self.target_key,
            force_refresh=self.force_refresh,
        )

    @classmethod
    def from_queue_payload(
        cls,
        *,
        target_type: str,
        target_key: str,
        force_refresh: bool = False,
    ) -> BeatmapFetchTarget:
        """Worker queue payloadからfetch targetを復元する.

        Args:
            target_type (str): queue payloadに格納されたtarget type.
            target_key (str): queue payloadに格納されたlookup key.
            force_refresh (bool): queue payloadに格納されたforce refresh指定.

        Returns:
            BeatmapFetchTarget: typed target typeを持つfetch target.

        Raises:
            ValueError: target_typeが未対応か,target_keyが空文字列の場合.
        """
        return cls(
            target_type=BeatmapFetchTargetKind(target_type),
            target_key=target_key,
            force_refresh=force_refresh,
        )

    @classmethod
    def metadata_by_beatmap_id(
        cls, beatmap_id: int, *, force_refresh: bool = False
    ) -> BeatmapFetchTarget:
        """Beatmap IDを指定したmetadata fetch targetを作る.

        Args:
            beatmap_id (int): metadataを取得するbeatmap ID.
            force_refresh (bool): cached状態にかかわらずrefreshを要求するか.

        Returns:
            BeatmapFetchTarget: METADATA_BY_BEATMAP_IDを持つfetch target.
        """
        return cls(
            target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAP_ID,
            target_key=str(beatmap_id),
            force_refresh=force_refresh,
        )

    @classmethod
    def metadata_by_beatmapset_id(
        cls, beatmapset_id: int, *, force_refresh: bool = False
    ) -> BeatmapFetchTarget:
        """Beatmapset IDを指定したmetadata fetch targetを作る.

        Args:
            beatmapset_id (int): metadataを取得するbeatmapset ID.
            force_refresh (bool): cached状態にかかわらずrefreshを要求するか.

        Returns:
            BeatmapFetchTarget: METADATA_BY_BEATMAPSET_IDを持つfetch target.
        """
        return cls(
            target_type=BeatmapFetchTargetKind.METADATA_BY_BEATMAPSET_ID,
            target_key=str(beatmapset_id),
            force_refresh=force_refresh,
        )

    @classmethod
    def metadata_by_checksum(
        cls, checksum_md5: str, *, force_refresh: bool = False
    ) -> BeatmapFetchTarget:
        """MD5 checksumを指定したmetadata fetch targetを作る.

        Args:
            checksum_md5 (str): metadataを取得するbeatmapのMD5 checksum.
            force_refresh (bool): cached状態にかかわらずrefreshを要求するか.

        Returns:
            BeatmapFetchTarget: METADATA_BY_CHECKSUMを持つfetch target.
        """
        return cls(
            target_type=BeatmapFetchTargetKind.METADATA_BY_CHECKSUM,
            target_key=checksum_md5,
            force_refresh=force_refresh,
        )

    @classmethod
    def file_by_beatmap_id(cls, beatmap_id: int) -> BeatmapFetchTarget:
        """Beatmap IDを指定したosu file fetch targetを作る.

        Args:
            beatmap_id (int): osu fileを取得するbeatmap ID.

        Returns:
            BeatmapFetchTarget: FILE_BY_BEATMAP_IDを持つfetch target.
        """
        return cls(
            target_type=BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID,
            target_key=str(beatmap_id),
        )


@dataclass(slots=True, frozen=True)
class BeatmapFetchRecord:
    """Fetch queue上の取得試行状態を表す.

    Attributes:
        target (BeatmapFetchTarget): 試行するmetadataまたはfile取得対象.
        status (BeatmapFetchState): 現在の取得試行状態.
        attempt_count (int): これまでの取得試行回数.
        last_error (str | None): 直近失敗の診断message. 成功または未試行時はNone.
        pending_since (datetime | None): pending状態を開始した日時. pendingでない場合はNone.
        last_attempted_at (datetime | None): 最後に取得を試行した日時. 未試行時はNone.
    """

    target: BeatmapFetchTarget
    status: BeatmapFetchState
    attempt_count: int
    last_error: str | None
    pending_since: datetime | None
    last_attempted_at: datetime | None


# ---------------------------------------------------------------------------
# Provider contracts -- snapshot types and metadata provider Protocol
# ---------------------------------------------------------------------------


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
        _validate_md5(self.checksum_md5)


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


class BeatmapFileSource(Enum):
    """Osu fileを取得したsourceを表す閉集合.

    Attributes:
        OFFICIAL (str): 現行公式sourceから取得したことを示す値.
        LEGACY_OFFICIAL (str): legacy公式sourceから取得したことを示す値.
        MIRROR (str): mirror sourceから取得したことを示す値.
        OSU_CURRENT (str): 現行osu! endpointから取得したことを示す値.
        OSU_LEGACY (str): legacy osu! endpointから取得したことを示す値.
        COMMUNITY_MIRROR (str): community mirrorから取得したことを示す値.
        ARCHIVE_EXTRACTED (str): archiveから抽出したことを示す値.
    """

    OFFICIAL = "official"
    LEGACY_OFFICIAL = "legacy_official"
    MIRROR = "mirror"
    OSU_CURRENT = "osu_current"
    OSU_LEGACY = "osu_legacy"
    COMMUNITY_MIRROR = "community_mirror"
    ARCHIVE_EXTRACTED = "archive_extracted"


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
