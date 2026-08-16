"""Beatmap domainの状態値と分類値を定義するmodule."""

from enum import Enum


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
