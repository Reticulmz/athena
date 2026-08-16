"""Beatmap metadataとfetch targetおよびfile attachment契約を検証するmodule.

Official statusとローカル上書きおよびworker queue payloadのdomain不変条件を対象にする.
"""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from enum import Enum

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchQueuePayload,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFetchTargetKind,
    BeatmapFileAttachment,
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapMetadataLookupKind,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
    map_external_status,
)

_NOW = datetime(2026, 6, 4, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_CHECKSUM = "0123456789abcdef0123456789abcdef"


def _make_beatmap(
    *,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    local_status_override: LocalBeatmapStatus | None = None,
    source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    source_verification: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    file_attachment: BeatmapFileAttachment | None = None,
) -> Beatmap:
    """Beatmap状態を検証するための一貫したfixture値を作る.

    Args:
        official_status (BeatmapRankStatus): providerが示す公式公開状態.
        local_status_override (LocalBeatmapStatus | None): operatorが指定するローカル状態上書き.
        source (BeatmapMetadataSource): metadataを得たsource.
        source_verification (BeatmapSourceVerification): source情報の検証状態.
        file_attachment (BeatmapFileAttachment | None): 利用可能なosu file attachment.

    Returns:
        Beatmap: 指定状態と固定したdifficulty metadataを持つbeatmap.

    Raises:
        ValueError: checksumまたはローカル状態上書きがdomain不変条件に反する場合.
        TypeError: local_status_overrideがLocalBeatmapStatusまたはNoneでない場合.
    """
    return Beatmap(
        id=2_000,
        beatmapset_id=1_000,
        checksum_md5=_CHECKSUM,
        mode=BeatmapMode.OSU,
        version="Another",
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=official_status,
        official_status_source=source,
        official_status_verified=source_verification,
        local_status_override=local_status_override,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=(
            BeatmapFileState.AVAILABLE if file_attachment is not None else BeatmapFileState.MISSING
        ),
        file_attachment=file_attachment,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _make_attachment() -> BeatmapFileAttachment:
    """Beatmap file attachmentの標準fixtureを作る.

    Returns:
        BeatmapFileAttachment: 固定したbeatmap IDとBlob IDおよび検証日時を持つattachment.
    """
    return BeatmapFileAttachment(
        beatmap_id=2_000,
        blob_id=55,
        checksum_md5=_CHECKSUM,
        source=BeatmapFileSource.OFFICIAL,
        original_filename="2000.osu",
        fetched_at=_NOW,
        verified_at=_NOW,
    )


def test_rank_status_enum_preserves_approved_as_official_status() -> None:
    """BeatmapRankStatusがAPPROVEDを公式公開状態として保持することを検証する.

    enum型と主要memberを確認しofficial providerから得たapproved状態を失わないことを確認する.

    Returns:
        None: 公式公開状態enumの検証を完了する.
    """
    assert issubclass(BeatmapRankStatus, Enum)
    assert BeatmapRankStatus.APPROVED.value == "approved"
    assert BeatmapRankStatus.RANKED.value == "ranked"
    assert BeatmapRankStatus.LOVED.value == "loved"
    assert BeatmapRankStatus.UNKNOWN.value == "unknown"


def test_local_status_enum_excludes_approved() -> None:
    """LocalBeatmapStatusがAPPROVEDをローカル上書きに含めないことを検証する.

    local overrideの値集合を調べてapprovedが不在でありrankedは選択できることを確認する.

    Returns:
        None: ローカル状態enumの検証を完了する.
    """
    assert "approved" not in {status.value for status in LocalBeatmapStatus}
    assert LocalBeatmapStatus.RANKED.value == "ranked"


def test_external_status_maps_not_submitted() -> None:
    """外部providerのnot_submitted値を専用statusへ変換することを検証する.

    Returns:
        None: not_submittedがUNKNOWNではなくNOT_SUBMITTEDになることを検証して完了する.
    """
    assert map_external_status(" not_submitted ") is BeatmapRankStatus.NOT_SUBMITTED


def test_fetch_target_exposes_typed_metadata_lookup() -> None:
    """Beatmapset metadata fetch targetがtyped lookupとqueue payloadを返すことを検証する.

    beatmapset IDでtargetを作成しprovider lookupのkindと整数値およびworker payloadを確認する.

    Returns:
        None: metadata fetch target変換の検証を完了する.
    """
    target = BeatmapFetchTarget.metadata_by_beatmapset_id(1234)

    lookup = target.metadata_lookup_target()

    assert target.kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAPSET_ID
    assert lookup.kind is BeatmapMetadataLookupKind.BEATMAPSET_ID
    assert lookup.int_value() == 1234
    assert target.queue_payload() == BeatmapFetchQueuePayload(
        target_type="metadata:beatmapset",
        target_key="1234",
    )
    assert target.queue_payload().force_refresh is False


def test_fetch_target_restores_worker_queue_payload() -> None:
    """Worker queue payloadからfile fetch targetを復元できることを検証する.

    file targetを表すprimitive値を復元しfile kindとforce refresh defaultおよびbeatmap IDを確認する.

    Returns:
        None: queue payload復元の検証を完了する.
    """
    target = BeatmapFetchTarget.from_queue_payload(
        target_type="file:beatmap",
        target_key="2000",
    )

    assert target.kind is BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID
    assert target.force_refresh is False
    assert target.is_file_fetch
    assert target.file_beatmap_id() == 2000


@pytest.mark.parametrize(
    ("target_type", "target_key"),
    [
        ("metadata:beatmap", "0"),
        ("metadata:beatmapset", "-1"),
        ("file:beatmap", "not-an-id"),
        ("metadata:beatmap", "01"),
        ("metadata:beatmapset", " 1"),
        ("file:beatmap", "+1"),
    ],
)
def test_fetch_target_rejects_invalid_id_key(target_type: str, target_key: str) -> None:
    """ID型fetch targetが正規形の正整数でないkeyを生成時に拒否することを検証する.

    Args:
        target_type (str): IDをlookup keyに使うfetch target type.
        target_key (str): 0,負数,非整数,または非正規形の拒否対象key.

    Returns:
        None: 不正なID keyがValueErrorになることを検証して完了する.
    """
    with pytest.raises(ValueError, match="target_key must be a canonical positive integer"):
        _ = BeatmapFetchTarget.from_queue_payload(
            target_type=target_type,
            target_key=target_key,
        )


def test_fetch_target_roundtrips_force_refresh_queue_payload() -> None:
    """Force refresh指定を含むmetadata targetがqueue payloadを往復することを検証する.

    refreshを要求するtargetをpayloadへ変換して復元しflagとtarget identityが保たれることを確認する.

    Returns:
        None: force refresh payload往復の検証を完了する.
    """
    target = BeatmapFetchTarget.metadata_by_beatmap_id(2000, force_refresh=True)

    payload = target.queue_payload()
    restored = BeatmapFetchTarget.from_queue_payload(
        target_type=payload.target_type,
        target_key=payload.target_key,
        force_refresh=payload.force_refresh,
    )

    assert payload == BeatmapFetchQueuePayload(
        target_type="metadata:beatmap",
        target_key="2000",
        force_refresh=True,
    )
    assert restored.force_refresh is True
    assert restored == BeatmapFetchTarget.metadata_by_beatmap_id(2000)


def test_metadata_lookup_rejects_file_fetch_target() -> None:
    """File fetch targetをmetadata lookupへ変換できないことを検証する.

    file targetからmetadata lookupを要求しdomainがValueErrorで用途の混同を拒否することを確認する.

    Returns:
        None: file target拒否の検証を完了する.
    """
    target = BeatmapFetchTarget.file_by_beatmap_id(2000)

    with pytest.raises(ValueError, match="file fetch target"):
        _ = target.metadata_lookup_target()


def test_beatmap_dataclass_contains_identity_status_source_and_file_fields() -> None:
    """Beatmapがidentityとstatusおよびfile取得状態の全fieldを持つことを検証する.

    dataclass field名を期待集合と比較しdomain snapshotの構造が変わらないことを確認する.

    Returns:
        None: beatmap field構造の検証を完了する.
    """
    expected = {
        "id",
        "beatmapset_id",
        "checksum_md5",
        "mode",
        "version",
        "total_length",
        "hit_length",
        "max_combo",
        "bpm",
        "cs",
        "od",
        "ar",
        "hp",
        "difficulty_rating",
        "official_status",
        "official_status_source",
        "official_status_verified",
        "official_last_updated_at",
        "local_status_override",
        "local_status_override_changed_at",
        "metadata_fetch_state",
        "file_state",
        "file_attachment",
        "last_fetched_at",
        "next_refresh_at",
    }

    assert hasattr(Beatmap, "__slots__")
    assert {field.name for field in fields(Beatmap)} == expected


def test_effective_status_uses_official_status_without_local_override() -> None:
    """ローカル上書きがない場合にeffective_statusが公式状態を返すことを検証する.

    APPROVEDの公式状態だけを持つbeatmapを生成し採用状態が同じofficial memberになることを確認する.

    Returns:
        None: 公式状態採用の検証を完了する.
    """
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.APPROVED)

    assert beatmap.official_status is BeatmapRankStatus.APPROVED
    assert beatmap.local_status_override is None
    assert beatmap.effective_status is BeatmapRankStatus.APPROVED


def test_effective_status_uses_local_override_when_present() -> None:
    """ローカル上書きがある場合にeffective_statusが上書き状態を返すことを検証する.

    PENDINGの公式状態にRANKED overrideを指定し採用状態がoperator指定へ切り替わることを確認する.

    Returns:
        None: ローカル状態上書きの検証を完了する.
    """
    beatmap = _make_beatmap(
        official_status=BeatmapRankStatus.PENDING,
        local_status_override=LocalBeatmapStatus.RANKED,
    )

    assert beatmap.official_status is BeatmapRankStatus.PENDING
    assert beatmap.local_status_override is LocalBeatmapStatus.RANKED
    assert beatmap.effective_status is BeatmapRankStatus.RANKED


def test_beatmap_rejects_approved_as_runtime_local_override() -> None:
    """APPROVEDをruntime local overrideに指定できないことを検証する.

    公式状態enumのAPPROVEDをlocal_status_overrideへ渡しValueErrorが返ることを確認する.

    Returns:
        None: 不正なローカル上書き拒否の検証を完了する.
    """
    with pytest.raises(ValueError, match="Approved cannot be used as a local override"):
        _ = _make_beatmap(
            local_status_override=BeatmapRankStatus.APPROVED,  # pyright: ignore[reportArgumentType]
        )


def test_beatmap_rejects_attachment_owned_by_another_beatmap() -> None:
    """Beatmapが別beatmap所有のfile attachmentを拒否することを検証する.

    Returns:
        None: attachment所有IDの不一致がValueErrorになることを検証して完了する.
    """
    attachment = replace(_make_attachment(), beatmap_id=9_999)

    with pytest.raises(ValueError, match="must match Beatmap"):
        _ = _make_beatmap(file_attachment=attachment)


def test_beatmap_distinguishes_source_and_verification() -> None:
    """Beatmapがmetadata sourceと検証状態を別fieldとして保持することを検証する.

    MIRROR sourceとUNVERIFIED状態を指定して出所とtrust判断が混同されないことを確認する.

    Returns:
        None: sourceとverification分離の検証を完了する.
    """
    beatmap = _make_beatmap(
        source=BeatmapMetadataSource.MIRROR,
        source_verification=BeatmapSourceVerification.UNVERIFIED,
    )

    assert beatmap.official_status_source is BeatmapMetadataSource.MIRROR
    assert beatmap.official_status_verified is BeatmapSourceVerification.UNVERIFIED


def test_file_attachment_metadata_references_blob_without_body_bytes() -> None:
    """Beatmap file attachmentがBlob参照だけを持ちbodyを持たないことを検証する.

    attachmentを持つbeatmapを生成しBlob IDを保持してcontent fieldを持たないことを確認する.

    Returns:
        None: attachment metadata境界の検証を完了する.
    """
    attachment = _make_attachment()
    beatmap = _make_beatmap(file_attachment=attachment)

    assert attachment.id is None
    assert attachment.blob_id == 55
    assert attachment.checksum_md5 == _CHECKSUM
    assert attachment.original_filename == "2000.osu"
    assert not hasattr(attachment, "body")
    assert not hasattr(attachment, "content")
    assert beatmap.file_state is BeatmapFileState.AVAILABLE
    assert beatmap.file_attachment == attachment


def test_file_attachment_preserves_persistent_identity_when_available() -> None:
    """永続化済みBeatmapFileAttachmentが正のIDを保持することを検証する.

    attachment IDを指定して生成しrepositoryから得たidentityとBlob参照を取得できることを確認する.

    Returns:
        None: 永続attachment identityの検証を完了する.
    """
    attachment = BeatmapFileAttachment(
        beatmap_id=2_000,
        blob_id=55,
        checksum_md5=_CHECKSUM,
        source=BeatmapFileSource.OFFICIAL,
        original_filename="2000.osu",
        fetched_at=_NOW,
        verified_at=_NOW,
        id=7,
    )

    assert attachment.id == 7
    assert attachment.blob_id == 55


def test_file_attachment_rejects_non_positive_persistent_identity() -> None:
    """BeatmapFileAttachmentが非正の永続IDを拒否することを検証する.

    IDを0として生成しrepository identityの不変条件がValueErrorで保護されることを確認する.

    Returns:
        None: 非正attachment ID拒否の検証を完了する.
    """
    with pytest.raises(ValueError, match="id must be positive"):
        _ = BeatmapFileAttachment(
            beatmap_id=2_000,
            blob_id=55,
            checksum_md5=_CHECKSUM,
            source=BeatmapFileSource.OFFICIAL,
            original_filename="2000.osu",
            fetched_at=_NOW,
            verified_at=_NOW,
            id=0,
        )


def test_beatmapset_groups_known_beatmaps_and_status_metadata() -> None:
    """BeatmapSetがdifficulty群と公式status metadataを保持することを検証する.

    既知のbeatmapを含むsetを生成しslot利用とdifficulty tupleおよび公式sourceを確認する.

    Returns:
        None: beatmapset groupingの検証を完了する.
    """
    beatmap = _make_beatmap()
    beatmapset = BeatmapSet(
        id=1_000,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        creator="Realazy",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )

    assert hasattr(BeatmapSet, "__slots__")
    assert beatmapset.id == 1_000
    assert beatmapset.beatmaps == (beatmap,)
    assert beatmapset.official_status is BeatmapRankStatus.RANKED
    assert beatmapset.official_status_source is BeatmapMetadataSource.OFFICIAL


def test_beatmapset_rejects_beatmap_owned_by_another_set() -> None:
    """BeatmapSetが別set所有のdifficultyを拒否することを検証する.

    Returns:
        None: child beatmapの所有ID不一致がValueErrorになることを検証して完了する.
    """
    beatmap = replace(_make_beatmap(), beatmapset_id=9_999)

    with pytest.raises(ValueError, match="must match BeatmapSet"):
        _ = BeatmapSet(
            id=1_000,
            artist="Camellia",
            title="Exit This Earth's Atomosphere",
            creator="Realazy",
            artist_unicode=None,
            title_unicode=None,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(beatmap,),
            last_fetched_at=_NOW,
            next_refresh_at=_NEXT_REFRESH,
        )


def test_beatmapset_snapshot_rejects_beatmap_owned_by_another_set() -> None:
    """BeatmapsetSnapshotが別set所有のchild snapshotを拒否することを検証する.

    Returns:
        None: child snapshotの所有ID不一致がValueErrorになることを検証して完了する.
    """
    beatmap = BeatmapSnapshot(
        beatmap_id=2_000,
        beatmapset_id=9_999,
        checksum_md5=_CHECKSUM,
        mode=BeatmapMode.OSU,
        version="Another",
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
    )

    with pytest.raises(
        ValueError,
        match="must match BeatmapsetSnapshot",
    ):
        _ = BeatmapsetSnapshot(
            beatmapset_id=1_000,
            artist="Camellia",
            title="Exit This Earth's Atomosphere",
            creator="Realazy",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(beatmap,),
        )
