"""外部APIのJSONレスポンスをprovider非依存のスナップショットへ変換する."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
    map_external_status,
)
from osu_server.shared.checksums import is_lowercase_md5_hexdigest

_ZERO_MD5 = "0" * 32


class _BeatmapJSON(TypedDict, total=False):
    """変換処理が読むosu! API v2ビートマップJSONの部分型.

    Attributes:
        id (int): ビートマップID.
        beatmapset_id (int): 所属するビートマップセットID.
        checksum (str): ビートマップファイルのMD5チェックサム.
        mode (str): osu! APIが返すゲームモード名.
        version (str): 難易度名.
        status (str): osu! APIが返す公開status名.
        total_length (int | None): 総再生時間(秒).
        hit_length (int | None): オブジェクト密度を除いた再生時間(秒).
        max_combo (int | None): 最大コンボ数.
        bpm (float | None): BPM.
        cs (float | None): Circle Size.
        accuracy (float | None): Overall Difficulty.
        ar (float | None): Approach Rate.
        drain (float | None): HP Drain.
        difficulty_rating (float | None): 難易度rating.
        last_update (str | None): API互換レスポンスの最終更新日時文字列.
        last_updated (str | None): API v2の最終更新日時文字列.
        beatmapset (_BeatmapsetJSON): 親ビートマップセットの埋め込みJSON.

    Notes:
        ``total=False`` のため,外部APIが省略するfieldを含め全fieldは任意である.
    """

    id: int
    beatmapset_id: int
    checksum: str
    mode: str
    version: str
    status: str
    total_length: int | None
    hit_length: int | None
    max_combo: int | None
    bpm: float | None
    cs: float | None
    accuracy: float | None
    ar: float | None
    drain: float | None
    difficulty_rating: float | None
    last_update: str | None
    last_updated: str | None
    beatmapset: _BeatmapsetJSON


class _BeatmapsetJSON(TypedDict, total=False):
    """変換処理が読むosu! API v2ビートマップセットJSONの部分型.

    Attributes:
        id (int): ビートマップセットID.
        artist (str): 曲のartist名.
        title (str): 曲名.
        creator (str): ビートマップセット作成者名.
        artist_unicode (str | None): Unicode表記のartist名.
        title_unicode (str | None): Unicode表記の曲名.
        source (str | None): 曲の出典文字列.
        tags (str | list[str] | None): beatmapset tag.
        status (str): osu! APIが返す公開status名.
        submitted_date (str | None): ビートマップセットの投稿日時文字列.
        ranked_date (str | None): ビートマップセットのranked日時文字列.
        last_updated (str | None): ビートマップセットの最終更新日時文字列.
        beatmaps (list[_BeatmapJSON]): 内包するビートマップJSON列.

    Notes:
        ``total=False`` のため,外部APIが省略するfieldを含め全fieldは任意である.
    """

    id: int
    artist: str
    title: str
    creator: str
    artist_unicode: str | None
    title_unicode: str | None
    source: str | None
    tags: str | list[str] | None
    status: str
    submitted_date: str | None
    ranked_date: str | None
    last_updated: str | None
    beatmaps: list[_BeatmapJSON]


def beatmap_json_to_snapshot(
    data: dict[str, object],
    *,
    now: datetime | None = None,
    source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    verification: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
) -> BeatmapsetSnapshot:
    """公式API v2のビートマップまたはセットJSONをスナップショットへ変換する.

    Args:
        data (dict[str, object]): ビートマップ単体または ``beatmaps`` を持つセットのJSON object.
        now (datetime | None): 取得日時として保存するUTC日時. ``None`` なら現在のUTC日時を使う.
        source (BeatmapMetadataSource): 変換結果へ記録するメタデータsource.
        verification (BeatmapSourceVerification): source由来の検証状態.

    Returns:
        BeatmapsetSnapshot: 外部statusと日時をdomain値へ変換したスナップショット.
    """
    _now = now or datetime.now(UTC)
    if "beatmaps" in data:
        return _from_beatmapset_json(
            cast("_BeatmapsetJSON", cast("object", data)),
            now=_now,
            source=source,
            verification=verification,
        )
    return _from_beatmap_json(
        cast("_BeatmapJSON", cast("object", data)),
        now=_now,
        source=source,
        verification=verification,
    )


def beatmap_v1_json_to_snapshot(
    items: Sequence[Mapping[str, object]],
    *,
    now: datetime | None = None,
    source: BeatmapMetadataSource = BeatmapMetadataSource.MIRROR,
    verification: BeatmapSourceVerification = BeatmapSourceVerification.UNVERIFIED,
) -> BeatmapsetSnapshot | None:
    """API v1互換のflatなビートマップ行をスナップショットへ変換する.

    Args:
        items (Sequence[Mapping[str, object]]): 同一ビートマップセットを表すv1互換JSON行.
        now (datetime | None): 取得日時として保存するUTC日時. ``None`` なら現在のUTC日時を使う.
        source (BeatmapMetadataSource): 変換結果へ記録するメタデータsource.
        verification (BeatmapSourceVerification): source由来の検証状態.

    Returns:
        BeatmapsetSnapshot | None: 変換したスナップショット. 入力行が空の場合は ``None``.
    """
    if not items:
        return None

    _now = now or datetime.now(UTC)
    first = items[0]
    beatmapset_id = _maybe_int(first.get("beatmapset_id")) or 0
    beatmaps = tuple(
        snapshot
        for item in items
        if (
            snapshot := _beatmap_v1_item_to_snapshot(
                item,
                beatmapset_id=beatmapset_id,
                now=_now,
                source=source,
                verification=verification,
            )
        )
        is not None
    )

    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist=_maybe_str(first.get("artist")) or "",
        title=_maybe_str(first.get("title")) or "",
        creator=_maybe_str(first.get("creator")) or "",
        source=source,
        verified=verification,
        official_status=map_external_status(_status_text(first.get("approved"))),
        official_status_source=source,
        official_status_verified=verification,
        beatmaps=beatmaps,
        artist_unicode=_maybe_str(first.get("artist_unicode")),
        title_unicode=_maybe_str(first.get("title_unicode")),
        last_fetched_at=_now,
        next_refresh_at=_now,
        official_submitted_at=_maybe_datetime(first.get("submitted_date")),
        official_ranked_at=(
            _maybe_datetime(first.get("ranked_date"))
            or _maybe_datetime(first.get("approved_date"))
        ),
        official_last_updated_at=(
            _maybe_datetime(first.get("last_updated")) or _maybe_datetime(first.get("last_update"))
        ),
        source_text=_maybe_str(first.get("source")) or "",
        tags=_tags_text(first.get("tags")),
    )


def _from_beatmap_json(
    data: _BeatmapJSON,
    *,
    now: datetime,
    source: BeatmapMetadataSource,
    verification: BeatmapSourceVerification,
) -> BeatmapsetSnapshot:
    """ビートマップ単体JSONを親セットを持つスナップショットへ変換する.

    Args:
        data (_BeatmapJSON): 親セットを ``beatmapset`` fieldへ含むビートマップJSON.
        now (datetime): 変換結果へ記録する取得日時.
        source (BeatmapMetadataSource): 変換結果へ記録するメタデータsource.
        verification (BeatmapSourceVerification): source由来の検証状態.

    Returns:
        BeatmapsetSnapshot: 単一ビートマップを含む親セットのスナップショット.
    """
    beatmapset_data = data.get("beatmapset") or {}
    return _from_beatmapset_json(
        {
            "id": beatmapset_data.get("id") or data.get("beatmapset_id") or 0,
            "artist": beatmapset_data.get("artist", ""),
            "title": beatmapset_data.get("title", ""),
            "creator": beatmapset_data.get("creator", ""),
            "artist_unicode": beatmapset_data.get("artist_unicode"),
            "title_unicode": beatmapset_data.get("title_unicode"),
            "source": beatmapset_data.get("source", ""),
            "tags": beatmapset_data.get("tags", ""),
            "status": beatmapset_data.get("status", ""),
            "submitted_date": beatmapset_data.get("submitted_date"),
            "ranked_date": beatmapset_data.get("ranked_date"),
            "last_updated": beatmapset_data.get("last_updated"),
            "beatmaps": [data],
        },
        now=now,
        source=source,
        verification=verification,
    )


def _from_beatmapset_json(
    data: _BeatmapsetJSON,
    *,
    now: datetime,
    source: BeatmapMetadataSource,
    verification: BeatmapSourceVerification,
) -> BeatmapsetSnapshot:
    """ビートマップセットJSONを親子スナップショットへ変換する.

    Args:
        data (_BeatmapsetJSON): ビートマップ列を含むセットJSON.
        now (datetime): 変換結果へ記録する取得日時.
        source (BeatmapMetadataSource): 変換結果へ記録するメタデータsource.
        verification (BeatmapSourceVerification): source由来の検証状態.

    Returns:
        BeatmapsetSnapshot: 全内包ビートマップを変換したセットのスナップショット.
    """
    beatmapset_id = data.get("id", 0)
    beatmapset_status = data.get("status", "")
    beatmapset_submitted_at = _maybe_datetime(data.get("submitted_date"))
    beatmapset_ranked_at = _maybe_datetime(data.get("ranked_date"))
    beatmapset_last_updated_at = _maybe_datetime(data.get("last_updated"))

    beatmaps_raw: list[_BeatmapJSON] = data.get("beatmaps") or []
    child_snapshots = tuple(
        snapshot
        for bm in beatmaps_raw
        if (
            snapshot := _beatmap_v2_item_to_snapshot(
                bm,
                beatmapset_id=beatmapset_id,
                beatmapset_last_updated_at=beatmapset_last_updated_at,
                now=now,
                source=source,
                verification=verification,
            )
        )
        is not None
    )

    _ = now
    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist=data.get("artist", ""),
        title=data.get("title", ""),
        creator=data.get("creator", ""),
        source=source,
        verified=verification,
        official_status=map_external_status(beatmapset_status),
        official_status_source=source,
        official_status_verified=verification,
        beatmaps=child_snapshots,
        artist_unicode=data.get("artist_unicode"),
        title_unicode=data.get("title_unicode"),
        last_fetched_at=now,
        next_refresh_at=now,
        official_submitted_at=beatmapset_submitted_at,
        official_ranked_at=beatmapset_ranked_at,
        official_last_updated_at=beatmapset_last_updated_at,
        source_text=_maybe_str(data.get("source")) or "",
        tags=_tags_text(data.get("tags")),
    )


def _normalize_usable_checksum(value: object) -> str | None:
    """外部JSONのchecksumを永続化可能な小文字MD5へ正規化する.

    Args:
        value (object): 外部APIから受け取ったchecksum値.

    Returns:
        str | None: 小文字MD5 checksum. 欠損,不正形式,all-zero値ならNone.
    """
    checksum = (_maybe_str(value) or "").strip().lower()
    if checksum == _ZERO_MD5 or not is_lowercase_md5_hexdigest(checksum):
        return None
    return checksum


def _beatmap_v1_item_to_snapshot(
    item: Mapping[str, object],
    *,
    beatmapset_id: int,
    now: datetime,
    source: BeatmapMetadataSource,
    verification: BeatmapSourceVerification,
) -> BeatmapSnapshot | None:
    """API v1互換行を保存可能なchild snapshotへ変換する.

    Args:
        item (Mapping[str, object]): v1互換のchild beatmap行.
        beatmapset_id (int): 親beatmapset ID.
        now (datetime): 取得日時.
        source (BeatmapMetadataSource): 変換結果へ記録するmetadata source.
        verification (BeatmapSourceVerification): source由来の検証状態.

    Returns:
        BeatmapSnapshot | None: 保存可能なchild snapshot. 必須ID/checksum欠損時はNone.
    """
    beatmap_id = _maybe_int(item.get("beatmap_id")) or 0
    child_beatmapset_id = _maybe_int(item.get("beatmapset_id")) or beatmapset_id
    checksum_md5 = _normalize_usable_checksum(item.get("file_md5"))
    if beatmap_id <= 0 or child_beatmapset_id <= 0 or checksum_md5 is None:
        return None
    return BeatmapSnapshot(
        beatmap_id=beatmap_id,
        beatmapset_id=child_beatmapset_id,
        checksum_md5=checksum_md5,
        mode=_mode_text(item.get("mode")),
        version=_maybe_str(item.get("version")) or "",
        official_status=map_external_status(_status_text(item.get("approved"))),
        official_status_source=source,
        official_status_verified=verification,
        total_length=_maybe_int(item.get("total_length")),
        hit_length=_maybe_int(item.get("hit_length")),
        max_combo=_maybe_int(item.get("max_combo")),
        bpm=_maybe_float(item.get("bpm")),
        cs=_maybe_float(item.get("diff_size")),
        od=_maybe_float(item.get("diff_overall")),
        ar=_maybe_float(item.get("diff_approach")),
        hp=_maybe_float(item.get("diff_drain")),
        difficulty_rating=_maybe_float(item.get("difficultyrating")),
        last_fetched_at=now,
        next_refresh_at=now,
        official_last_updated_at=_maybe_datetime(item.get("last_update")),
    )


def _beatmap_v2_item_to_snapshot(
    bm: _BeatmapJSON,
    *,
    beatmapset_id: int,
    beatmapset_last_updated_at: datetime | None,
    now: datetime,
    source: BeatmapMetadataSource,
    verification: BeatmapSourceVerification,
) -> BeatmapSnapshot | None:
    """API v2互換child JSONを保存可能なsnapshotへ変換する.

    Args:
        bm (_BeatmapJSON): v2互換のchild beatmap JSON.
        beatmapset_id (int): 親beatmapset ID.
        beatmapset_last_updated_at (datetime | None): 親setの最終更新日時.
        now (datetime): 取得日時.
        source (BeatmapMetadataSource): 変換結果へ記録するmetadata source.
        verification (BeatmapSourceVerification): source由来の検証状態.

    Returns:
        BeatmapSnapshot | None: 保存可能なchild snapshot. 必須ID/checksum欠損時はNone.
    """
    beatmap_id = _maybe_int(bm.get("id")) or 0
    child_beatmapset_id = _maybe_int(bm.get("beatmapset_id")) or beatmapset_id
    checksum_md5 = _normalize_usable_checksum(bm.get("checksum"))
    if beatmap_id <= 0 or child_beatmapset_id <= 0 or checksum_md5 is None:
        return None
    return BeatmapSnapshot(
        beatmap_id=beatmap_id,
        beatmapset_id=child_beatmapset_id,
        checksum_md5=checksum_md5,
        mode=_mode_text(bm.get("mode")),
        version=bm.get("version", ""),
        official_status=map_external_status(bm.get("status", "")),
        official_status_source=source,
        official_status_verified=verification,
        total_length=bm.get("total_length"),
        hit_length=bm.get("hit_length"),
        max_combo=bm.get("max_combo"),
        bpm=_maybe_float(bm.get("bpm")),
        cs=_maybe_float(bm.get("cs")),
        od=_maybe_float(bm.get("accuracy")),
        ar=_maybe_float(bm.get("ar")),
        hp=_maybe_float(bm.get("drain")),
        difficulty_rating=_maybe_float(bm.get("difficulty_rating")),
        last_fetched_at=now,
        next_refresh_at=now,
        official_last_updated_at=(
            _maybe_datetime(bm.get("last_updated"))
            or _maybe_datetime(bm.get("last_update"))
            or beatmapset_last_updated_at
        ),
    )


def _tags_text(value: object) -> str:
    """外部JSON tag値を検索用文字列へ変換する.

    Args:
        value (object): APIが返したtags field.

    Returns:
        str: 文字列tagはそのまま返し, 文字列配列は空白で結合する. 未対応値は空文字列.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        items = cast("list[object] | tuple[object, ...]", value)
        return " ".join(item for item in items if isinstance(item, str))
    return ""


def _maybe_int(value: object) -> int | None:
    """外部JSON値をintへ安全に変換する.

    Args:
        value (object): 外部APIから受け取った変換対象値.

    Returns:
        int | None: 変換した整数. ``bool``, ``None``,不正な文字列,未対応型は ``None``.

    Notes:
        floatはPythonの ``int()`` と同じく小数部を切り捨てる.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _maybe_str(value: object) -> str | None:
    """外部JSON値を文字列として扱える場合だけ文字列化する.

    Args:
        value (object): 外部APIから受け取った変換対象値.

    Returns:
        str | None: 文字列値,またはint/floatを文字列化した値. 未対応型と ``None`` は ``None``.

    Notes:
        ``bool`` はPythonでは ``int`` のsubclassであるため ``"True"`` または ``"False"`` になる.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, int | float):
        return str(value)
    return None


def _maybe_datetime(value: object) -> datetime | None:
    """外部JSONのISO 8601日時をUTCのdatetimeへ変換する.

    Args:
        value (object): 文字列,数値,またはその他の外部API値.

    Returns:
        datetime | None: UTCへ正規化した日時. 不正,空,または未対応の値は ``None``.

    Notes:
        末尾 ``Z`` はUTC offsetへ置換し,timezoneなしの日時はUTCとして扱う.
    """
    text = _maybe_str(value)
    if text is None:
        return None
    normalized = text.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _mode_text(value: object) -> BeatmapMode:
    """外部JSONの数値または文字列modeをdomain enumへ変換する.

    Args:
        value (object): osu! APIが返すmode値.

    Returns:
        BeatmapMode: 定義済みmode. 未対応または不正な値は ``BeatmapMode.UNKNOWN``.
    """
    mode = _maybe_int(value)
    if mode is not None:
        return {
            0: BeatmapMode.OSU,
            1: BeatmapMode.TAIKO,
            2: BeatmapMode.FRUITS,
            3: BeatmapMode.MANIA,
        }.get(mode, BeatmapMode.UNKNOWN)
    text = (_maybe_str(value) or "").strip()
    try:
        return BeatmapMode(text)
    except ValueError:
        return BeatmapMode.UNKNOWN


def _status_text(value: object) -> str:
    """API v1互換の数値statusまたは文字列statusを外部status名へ変換する.

    Args:
        value (object): osu! APIが返す ``approved`` またはstatus値.

    Returns:
        str: 数値statusに対応する名称,または前後空白を除いた文字列. 未対応値は空文字列.
    """
    approved = _maybe_int(value)
    if approved is not None:
        return {
            -2: "graveyard",
            -1: "wip",
            0: "pending",
            1: "ranked",
            2: "approved",
            3: "qualified",
            4: "loved",
        }.get(approved, "")
    return (_maybe_str(value) or "").strip()


def _maybe_float(value: object) -> float | None:
    """外部JSON値をfloatへ安全に変換する.

    Args:
        value (object): 外部APIから受け取った変換対象値.

    Returns:
        float | None: 変換した浮動小数点数. ``bool``, ``None``,不正な文字列,未対応型は ``None``.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
