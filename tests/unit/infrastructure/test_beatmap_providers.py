"""Beatmap metadata providerのmappingとfallback契約を検証する."""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from osu_server.domain.beatmaps import (
    BeatmapMetadataProvider,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
    map_external_status,
)
from osu_server.infrastructure.beatmaps.mappers import (
    beatmap_json_to_snapshot,
    beatmap_v1_json_to_snapshot,
)
from osu_server.infrastructure.beatmaps.metadata_sources import (
    CompositeBeatmapMetadataProvider,
)
from tests.factories.beatmap import (
    FakeBeatmapMetadataProvider,
    FakeProviderResultKind,
    make_metadata_provider_response,
)

# ---------------------------------------------------------------------------
# Status mapping tests (exhaustive)
# ---------------------------------------------------------------------------


class TestMapExternalStatus:
    """External status文字列からBeatmapRankStatusへのmapping契約を検証する."""

    def test_ranked(self) -> None:
        """Ranked文字列をRANKED enumへ写す契約を検証する.

        ranked external statusを変換し, BeatmapRankStatus.RANKEDが返ることを確認する.

        Returns:
            None: ranked mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert map_external_status("ranked") is BeatmapRankStatus.RANKED

    def test_approved(self) -> None:
        """Approved文字列をAPPROVED enumへ写す契約を検証する.

        approved external statusを変換し, BeatmapRankStatus.APPROVEDが返ることを確認する.

        Returns:
            None: approved mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert map_external_status("approved") is BeatmapRankStatus.APPROVED

    def test_loved(self) -> None:
        """Loved文字列をLOVED enumへ写す契約を検証する.

        loved external statusを変換し, BeatmapRankStatus.LOVEDが返ることを確認する.

        Returns:
            None: loved mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert map_external_status("loved") is BeatmapRankStatus.LOVED

    def test_qualified(self) -> None:
        """Qualified文字列をQUALIFIED enumへ写す契約を検証する.

        qualified external statusを変換し, BeatmapRankStatus.QUALIFIEDが返ることを確認する.

        Returns:
            None: qualified mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert map_external_status("qualified") is BeatmapRankStatus.QUALIFIED

    def test_pending(self) -> None:
        """Pending文字列をPENDING enumへ写す契約を検証する.

        pending external statusを変換し, BeatmapRankStatus.PENDINGが返ることを確認する.

        Returns:
            None: pending mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert map_external_status("pending") is BeatmapRankStatus.PENDING

    def test_wip(self) -> None:
        """Wip文字列をWIP enumへ写す契約を検証する.

        wip external statusを変換し, BeatmapRankStatus.WIPが返ることを確認する.

        Returns:
            None: wip mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert map_external_status("wip") is BeatmapRankStatus.WIP

    def test_graveyard(self) -> None:
        """Graveyard文字列をGRAVEYARD enumへ写す契約を検証する.

        graveyard external statusを変換し, BeatmapRankStatus.GRAVEYARDが返ることを確認する.

        Returns:
            None: graveyard mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert map_external_status("graveyard") is BeatmapRankStatus.GRAVEYARD

    def test_unknown_string_returns_unknown(self) -> None:
        """Unknown文字列をUNKNOWN enumへ安全に写す契約を検証する.

        unknown statusを変換し, BeatmapRankStatus.UNKNOWNが返ることを確認する.

        Returns:
            None: unknown mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert map_external_status("unknown") is BeatmapRankStatus.UNKNOWN

    def test_nonexistent_status_returns_unknown(self) -> None:
        """将来追加される未定義statusをUNKNOWNへ写す契約を検証する.

        enumにないcategory文字列を変換し, BeatmapRankStatus.UNKNOWNが返ることを確認する.

        Returns:
            None: forward-compatible mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert map_external_status("some_future_category") is BeatmapRankStatus.UNKNOWN

    def test_empty_string_returns_unknown(self) -> None:
        """空status文字列をUNKNOWNへ写す契約を検証する.

        空文字列を変換し, BeatmapRankStatus.UNKNOWNが返ることを確認する.

        Returns:
            None: empty input mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert map_external_status("") is BeatmapRankStatus.UNKNOWN

    def test_case_insensitive(self) -> None:
        """External statusの大文字小文字を区別しない契約を検証する.

        rankedとgraveyardとlovedの大小文字variantを変換し, 各statusが同じenumへ写ることを確認する.

        Returns:
            None: case-insensitive mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert map_external_status("RANKED") is BeatmapRankStatus.RANKED
        assert map_external_status("Ranked") is BeatmapRankStatus.RANKED
        assert map_external_status("GRAVEYARD") is BeatmapRankStatus.GRAVEYARD
        assert map_external_status("Loved") is BeatmapRankStatus.LOVED

    def test_whitespace_handling(self) -> None:
        """External statusの前後whitespaceを除去する契約を検証する.

        空白とtabとnewlineを含むstatusを変換し, 正規化後のenumが返ることを確認する.

        Returns:
            None: whitespace normalizationを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert map_external_status("  ranked  ") is BeatmapRankStatus.RANKED
        assert map_external_status("\tpending\n") is BeatmapRankStatus.PENDING

    def test_all_known_statuses_are_mapped(self) -> None:
        """既知external status全件がUNKNOWN以外へ写る契約を検証する.

        known status集合を反復して変換し, 全resultがBeatmapRankStatus.UNKNOWNでないことを確認する.

        Returns:
            None: known status coverageを検証して完了し, 呼び出し側へ値を返さない.
        """
        known = {"ranked", "approved", "loved", "qualified", "pending", "wip", "graveyard"}
        for status_str in known:
            result = map_external_status(status_str)
            assert result is not BeatmapRankStatus.UNKNOWN, (
                f"Expected {status_str} to map to a known status, got UNKNOWN"
            )


# ---------------------------------------------------------------------------
# BeatmapSnapshot tests
# ---------------------------------------------------------------------------


class TestBeatmapSnapshot:
    """BeatmapSnapshotのfieldとimmutable dataclass契約を検証する."""

    def test_creation_with_required_fields(self) -> None:
        """Required fieldからBeatmapSnapshotを生成する契約を検証する.

        IDとchecksumとmodeとofficial statusを持つsnapshotを生成する.
        各主要fieldが入力値を保持することを確認する.

        Returns:
            None: required fieldの保存を検証して完了し, 呼び出し側へ値を返さない.
        """
        now = datetime.now(UTC)
        snap = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Another",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            last_fetched_at=now,
            next_refresh_at=now + timedelta(days=30),
        )
        assert snap.beatmap_id == 2000
        assert snap.beatmapset_id == 1000
        assert snap.mode is BeatmapMode.OSU
        assert snap.version == "Another"
        assert snap.official_status is BeatmapRankStatus.RANKED

    def test_default_values(self) -> None:
        """Optional metadata fieldが既定Noneになる契約を検証する.

        required fieldだけでsnapshotを生成し,
        local statusとgameplay statsとrefresh metadataがNoneとなることを確認する.

        Returns:
            None: optional fieldの既定値を検証して完了し, 呼び出し側へ値を返さない.
        """
        snap = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Normal",
            official_status=BeatmapRankStatus.UNKNOWN,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        )
        assert snap.local_status_override is None
        assert snap.total_length is None
        assert snap.hit_length is None
        assert snap.max_combo is None
        assert snap.bpm is None
        assert snap.cs is None
        assert snap.od is None
        assert snap.ar is None
        assert snap.hp is None
        assert snap.difficulty_rating is None
        assert snap.last_fetched_at is None
        assert snap.next_refresh_at is None
        assert snap.official_last_updated_at is None

    def test_frozen_immutable(self) -> None:
        """BeatmapSnapshotが生成後のfield変更を拒否する契約を検証する.

        valid snapshotを生成してbeatmap_idを代入し, FrozenInstanceErrorが送出されることを確認する.

        Returns:
            None: immutable snapshotを検証して完了し, 呼び出し側へ値を返さない.
        """
        snap = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Normal",
            official_status=BeatmapRankStatus.UNKNOWN,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        )
        with pytest.raises(FrozenInstanceError):
            snap.beatmap_id = 9999  # pyright: ignore[reportAttributeAccessIssue]

    def test_gameplay_stats_accept_none(self) -> None:
        """部分的gameplay statsを持つsnapshotが未提供statをNoneに保つ契約を検証する.

        csとodとarだけを渡してsnapshotを生成し, 提供値は保持され残りstatがNoneとなることを確認する.

        Returns:
            None: partial gameplay statsを検証して完了し, 呼び出し側へ値を返さない.
        """
        snap = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Expert",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            cs=4.5,
            od=8.0,
            ar=9.2,
        )
        assert snap.cs == 4.5
        assert snap.od == 8.0
        assert snap.ar == 9.2
        assert snap.hp is None
        assert snap.bpm is None

    def test_local_status_override_preserved(self) -> None:
        """Local status overrideがsnapshot生成後も保持される契約を検証する.

        official graveyardとlocal loved overrideを渡してsnapshotを生成する.
        local overrideがLOVEDとなることを確認する.

        Returns:
            None: local status保存を検証して完了し, 呼び出し側へ値を返さない.
        """
        snap = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Insane",
            official_status=BeatmapRankStatus.GRAVEYARD,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            local_status_override=LocalBeatmapStatus.LOVED,
        )
        assert snap.local_status_override is LocalBeatmapStatus.LOVED

    def test_invalid_checksum_raises(self) -> None:
        """不正なchecksumがBeatmapSnapshot生成を拒否する契約を検証する.

        MD5形式でないchecksumを渡してsnapshotを生成する.
        checksum_md5を示すValueErrorが送出されることを確認する.

        Returns:
            None: checksum validationを検証して完了し, 呼び出し側へ値を返さない.
        """
        with pytest.raises(ValueError, match="checksum_md5"):
            _ = BeatmapSnapshot(
                beatmap_id=2000,
                beatmapset_id=1000,
                checksum_md5="not-a-valid-md5",
                mode=BeatmapMode.OSU,
                version="Normal",
                official_status=BeatmapRankStatus.UNKNOWN,
                official_status_source=BeatmapMetadataSource.OFFICIAL,
                official_status_verified=BeatmapSourceVerification.UNVERIFIED,
            )

    def test_equals_by_value(self) -> None:
        """同一field値のBeatmapSnapshot同士がvalue equalityとなる契約を検証する.

        等価な2つのsnapshotを生成して比較し, dataclass equalityがTrueとなることを確認する.

        Returns:
            None: snapshot value equalityを検証して完了し, 呼び出し側へ値を返さない.
        """
        a = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Normal",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        b = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Normal",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        assert a == b


class TestBeatmapMetadataMapper:
    """External metadataの日付field mapping契約を検証する."""

    def test_v1_last_update_maps_to_official_last_updated_at(self) -> None:
        """V1 last_updateがbeatmapのofficial_last_updated_atへ写る契約を検証する.

        v1 JSONのlast_updateをsnapshotへ変換する.
        child beatmapの日時がUTC timestampと一致することを確認する.

        Returns:
            None: v1 timestamp mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        snapshot = beatmap_v1_json_to_snapshot(
            [
                {
                    "beatmap_id": "2000",
                    "beatmapset_id": "1000",
                    "file_md5": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
                    "mode": "0",
                    "version": "Insane",
                    "approved": "1",
                    "artist": "Camellia",
                    "title": "Exit This Earth's Atomosphere",
                    "creator": "Realazy",
                    "last_update": "2026-06-29 12:34:56",
                }
            ],
            now=datetime(2026, 6, 30, tzinfo=UTC),
        )

        assert snapshot is not None
        assert snapshot.beatmaps[0].official_last_updated_at == datetime(
            2026, 6, 29, 12, 34, 56, tzinfo=UTC
        )

    def test_v2_last_updated_maps_to_official_last_updated_at(self) -> None:
        """V2 beatmap last_updatedとset fallbackをofficial日時へ写す契約を検証する.

        v2 JSONをsnapshotへ変換し, explicit日時とset日時fallbackが各childに入ることを確認する.

        Returns:
            None: v2 timestamp mappingを検証して完了し, 呼び出し側へ値を返さない.
        """
        snapshot = beatmap_json_to_snapshot(
            {
                "id": 1000,
                "artist": "Camellia",
                "title": "Exit This Earth's Atomosphere",
                "creator": "Realazy",
                "status": "ranked",
                "last_updated": "2026-06-28T00:00:00Z",
                "beatmaps": [
                    {
                        "id": 2000,
                        "beatmapset_id": 1000,
                        "checksum": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
                        "mode": "osu",
                        "version": "Insane",
                        "status": "ranked",
                        "last_updated": "2026-06-29T12:34:56Z",
                    },
                    {
                        "id": 2001,
                        "beatmapset_id": 1000,
                        "checksum": "ffffffffffffffffffffffffffffffff",
                        "mode": "osu",
                        "version": "Another",
                        "status": "ranked",
                    },
                ],
            },
            now=datetime(2026, 6, 30, tzinfo=UTC),
        )

        assert snapshot.beatmaps[0].official_last_updated_at == datetime(
            2026, 6, 29, 12, 34, 56, tzinfo=UTC
        )
        assert snapshot.beatmaps[1].official_last_updated_at == datetime(2026, 6, 28, tzinfo=UTC)


# ---------------------------------------------------------------------------
# BeatmapsetSnapshot tests
# ---------------------------------------------------------------------------


class TestBeatmapsetSnapshot:
    """BeatmapsetSnapshotのsource provenanceとimmutable契約を検証する."""

    def test_creation_with_required_fields(self) -> None:
        """Required metadataとchild beatmapからBeatmapsetSnapshotを生成する契約を検証する.

        official sourceとverified childを渡してsnapshotを生成する.
        set IDとartistとsourceとchild数が一致することを確認する.

        Returns:
            None: required beatmapset fieldを検証して完了し, 呼び出し側へ値を返さない.
        """
        now = datetime.now(UTC)
        child = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Another",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        snap = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="Camellia",
            title="Exit This Earth's Atomosphere",
            creator="Realazy",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(child,),
            last_fetched_at=now,
            next_refresh_at=now + timedelta(days=30),
        )
        assert snap.beatmapset_id == 1000
        assert snap.artist == "Camellia"
        assert snap.title == "Exit This Earth's Atomosphere"
        assert snap.creator == "Realazy"
        assert snap.source is BeatmapMetadataSource.OFFICIAL
        assert snap.verified is BeatmapSourceVerification.VERIFIED
        assert len(snap.beatmaps) == 1

    def test_source_mirror_unverified(self) -> None:
        """Mirror sourceのsnapshotがUNVERIFIED provenanceを持つ契約を検証する.

        mirror sourceとunverified childでsnapshotを生成し,
        set sourceとverified flagとofficial sourceがmirrorとなることを確認する.

        Returns:
            None: mirror provenanceを検証して完了し, 呼び出し側へ値を返さない.
        """
        child = BeatmapSnapshot(
            beatmap_id=9999,
            beatmapset_id=8888,
            checksum_md5="ffffffffffffffffffffffffffffffff",
            mode=BeatmapMode.OSU,
            version="Normal",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.MIRROR,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        )
        snap = BeatmapsetSnapshot(
            beatmapset_id=8888,
            artist="Unknown Artist",
            title="Unknown Title",
            creator="Unknown Creator",
            source=BeatmapMetadataSource.MIRROR,
            verified=BeatmapSourceVerification.UNVERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.MIRROR,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
            beatmaps=(child,),
        )
        assert snap.source is BeatmapMetadataSource.MIRROR
        assert snap.verified is BeatmapSourceVerification.UNVERIFIED
        assert snap.official_status_source is BeatmapMetadataSource.MIRROR

    def test_official_source_verified(self) -> None:
        """Official sourceのsnapshotがVERIFIED provenanceを持つ契約を検証する.

        official sourceとverified childでsnapshotを生成し,
        sourceがOFFICIALかつverifiedがVERIFIEDとなることを確認する.

        Returns:
            None: official provenanceを検証して完了し, 呼び出し側へ値を返さない.
        """
        child = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Another",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        snap = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="Camellia",
            title="Exit This Earth's Atomosphere",
            creator="Realazy",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(child,),
        )
        assert snap.source is BeatmapMetadataSource.OFFICIAL
        assert snap.verified is BeatmapSourceVerification.VERIFIED

    def test_frozen_immutable(self) -> None:
        """BeatmapsetSnapshotが生成後のartist変更を拒否する契約を検証する.

        valid snapshotを生成してartistを代入し, FrozenInstanceErrorが送出されることを確認する.

        Returns:
            None: immutable beatmapsetを検証して完了し, 呼び出し側へ値を返さない.
        """
        child = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Normal",
            official_status=BeatmapRankStatus.UNKNOWN,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        )
        snap = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="Test",
            title="Test",
            creator="Test",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.UNKNOWN,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
            beatmaps=(child,),
        )
        with pytest.raises(FrozenInstanceError):
            snap.artist = "Changed"  # pyright: ignore[reportAttributeAccessIssue]

    def test_multiple_beatmaps(self) -> None:
        """BeatmapsetSnapshotが複数difficulty childを保持する契約を検証する.

        easyとhardの2childを持つsnapshotを生成する.
        child数と順序付きbeatmap IDが一致することを確認する.

        Returns:
            None: multiple child storageを検証して完了し, 呼び出し側へ値を返さない.
        """
        b1 = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Easy",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        b2 = BeatmapSnapshot(
            beatmap_id=2001,
            beatmapset_id=1000,
            checksum_md5="b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a1",
            mode=BeatmapMode.OSU,
            version="Hard",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        snap = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="Camellia",
            title="Test",
            creator="Mapper",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(b1, b2),
        )
        assert len(snap.beatmaps) == 2
        assert snap.beatmaps[0].beatmap_id == 2000
        assert snap.beatmaps[1].beatmap_id == 2001

    def test_unicode_fields_default_none(self) -> None:
        """Unicode artistとtitle fieldが既定Noneになる契約を検証する.

        unicode fieldを渡さずsnapshotを生成する.
        artist_unicodeとtitle_unicodeがNoneとなることを確認する.

        Returns:
            None: unicode既定値を検証して完了し, 呼び出し側へ値を返さない.
        """
        child = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Normal",
            official_status=BeatmapRankStatus.UNKNOWN,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        )
        snap = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="Artist",
            title="Title",
            creator="Creator",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.UNKNOWN,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
            beatmaps=(child,),
        )
        assert snap.artist_unicode is None
        assert snap.title_unicode is None

    def test_equals_by_value(self) -> None:
        """同一field値のBeatmapsetSnapshot同士がvalue equalityとなる契約を検証する.

        等価なchildを持つ2つのsnapshotを生成して比較する.
        dataclass equalityがTrueとなることを確認する.

        Returns:
            None: beatmapset value equalityを検証して完了し, 呼び出し側へ値を返さない.
        """
        child = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Normal",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        a = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="A",
            title="T",
            creator="C",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(child,),
        )
        child2 = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode=BeatmapMode.OSU,
            version="Normal",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        b = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="A",
            title="T",
            creator="C",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(child2,),
        )
        assert a == b


# ---------------------------------------------------------------------------
# BeatmapMetadataProvider Protocol tests
# ---------------------------------------------------------------------------


class TestBeatmapMetadataProviderProtocol:
    """BeatmapMetadataProviderのstructural protocol契約を検証する."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """BeatmapMetadataProviderがruntime protocol markerを持つ契約を検証する.

        Protocol classのinternal runtime markerを読み取る.
        runtime structural checkが有効であることを確認する.

        Returns:
            None: runtime protocol markerを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert hasattr(BeatmapMetadataProvider, "_is_runtime_protocol")

    def test_protocol_has_expected_methods(self) -> None:
        """Protocolが3種類のlookup methodを公開する契約を検証する.

        Protocol classのattributeを調べる.
        beatmap IDとset IDとchecksum用methodが全てあることを確認する.

        Returns:
            None: lookup API surfaceを検証して完了し, 呼び出し側へ値を返さない.
        """
        assert hasattr(BeatmapMetadataProvider, "lookup_by_beatmap_id")
        assert hasattr(BeatmapMetadataProvider, "lookup_by_beatmapset_id")
        assert hasattr(BeatmapMetadataProvider, "lookup_by_checksum")

    def test_fake_provider_satisfies_domain_protocol(self) -> None:
        """FactoryのFakeBeatmapMetadataProviderがdomain Protocolに適合する契約を検証する.

        fake providerを生成してisinstanceを実行する.
        BeatmapMetadataProviderとして認識されることを確認する.

        Returns:
            None: fake providerのprotocol適合を検証して完了し, 呼び出し側へ値を返さない.
        """
        assert isinstance(FakeBeatmapMetadataProvider(), BeatmapMetadataProvider)

    def test_composite_satisfies_provider_protocol(self) -> None:
        """CompositeBeatmapMetadataProviderがmetadata Protocolに適合する契約を検証する.

        null providerのcompositeを生成してisinstanceを実行する.
        BeatmapMetadataProviderとして認識されることを確認する.

        Returns:
            None: compositeのprotocol適合を検証して完了し, 呼び出し側へ値を返さない.
        """
        provider = CompositeBeatmapMetadataProvider(
            official=_make_null_provider(),
            mirror=_make_null_provider(),
        )
        assert isinstance(provider, BeatmapMetadataProvider)


# ---------------------------------------------------------------------------
# CompositeBeatmapMetadataProvider chain tests
# ---------------------------------------------------------------------------


class TestCompositeBeatmapMetadataProvider:
    """Officialからmirrorへ連鎖するmetadata provider契約を検証する."""

    async def test_official_success_does_not_try_mirror(self) -> None:
        """Official成功時にmirrorを呼ばずofficial結果を返す契約を検証する.

        snapshotを返すofficialとNoneを返すmirrorでbeatmap ID lookupを実行する.
        official結果とcall countを確認する.

        Returns:
            None: official firstのshort circuitを検証して完了し, 呼び出し側へ値を返さない.
        """
        official = _CountingProvider("official", _make_provider_test_snapshot(beatmapset_id=1000))
        mirror = _CountingProvider("mirror", None)

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        result = await composite.lookup_by_beatmap_id(2000)

        assert result is not None
        assert result.beatmapset_id == 1000
        assert official.lookup_by_beatmap_id_calls == 1
        assert mirror.lookup_by_beatmap_id_calls == 0

    async def test_official_none_falls_back_to_mirror(self) -> None:
        """OfficialがNoneならmirror結果へfallbackする契約を検証する.

        None officialとsnapshot mirrorでbeatmap ID lookupを実行し,
        mirror snapshotと両providerのcall countを確認する.

        Returns:
            None: None fallbackを検証して完了し, 呼び出し側へ値を返さない.
        """
        official = _CountingProvider("official", None)
        mirror = _CountingProvider("mirror", _make_provider_test_snapshot(beatmapset_id=8888))

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        result = await composite.lookup_by_beatmap_id(9999)

        assert result is not None
        assert result.beatmapset_id == 8888
        assert official.lookup_by_beatmap_id_calls == 1
        assert mirror.lookup_by_beatmap_id_calls == 1

    async def test_both_return_none(self) -> None:
        """両providerがNoneならcompositeもNoneを返す契約を検証する.

        Noneを返すofficialとmirrorでbeatmapset ID lookupを実行する.
        resultがNoneで両call countが1となることを確認する.

        Returns:
            None: empty lookup chainを検証して完了し, 呼び出し側へ値を返さない.
        """
        official = _CountingProvider("official", None)
        mirror = _CountingProvider("mirror", None)

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        result = await composite.lookup_by_beatmapset_id(5000)

        assert result is None
        assert official.lookup_by_beatmapset_id_calls == 1
        assert mirror.lookup_by_beatmapset_id_calls == 1

    async def test_official_exception_falls_back_to_mirror(self) -> None:
        """Official例外後もmirror lookupを試す契約を検証する.

        timeoutを送出するofficialとsnapshot mirrorでbeatmap ID lookupを実行する.
        mirror snapshotが返ることを確認する.

        Returns:
            None: exception fallbackを検証して完了し, 呼び出し側へ値を返さない.
        """
        official = _RaisingProvider(
            "official",
            BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TIMEOUT,
                source="official",
                lookup_key="2000",
                message="timeout",
            ),
        )
        mirror = _CountingProvider("mirror", _make_provider_test_snapshot(beatmapset_id=7777))

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        result = await composite.lookup_by_beatmap_id(2000)

        assert result is not None
        assert result.beatmapset_id == 7777

    async def test_both_raise_returns_none(self) -> None:
        """両providerが例外ならcompositeがNoneを返す契約を検証する.

        timeout officialとnot-found mirrorでchecksum lookupを実行する.
        callerへNoneが返ることを確認する.

        Returns:
            None: exhausted exception chainを検証して完了し, 呼び出し側へ値を返さない.
        """
        official = _RaisingProvider(
            "official",
            BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TIMEOUT,
                source="official",
                lookup_key="2000",
                message="timeout",
            ),
        )
        mirror = _RaisingProvider(
            "mirror",
            BeatmapSourceError(
                category=BeatmapSourceErrorCategory.NOT_FOUND,
                source="mirror",
                lookup_key="2000",
                message="not found",
            ),
        )

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        result = await composite.lookup_by_checksum("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")

        assert result is None

    async def test_lookup_by_beatmap_id_delegates(self) -> None:
        """Beatmap ID lookupがsub-providerの同名methodへ委譲される契約を検証する.

        snapshot officialでbeatmap ID lookupを実行し,
        officialのlast_called_methodがlookup_by_beatmap_idとなることを確認する.

        Returns:
            None: beatmap ID delegationを検証して完了し, 呼び出し側へ値を返さない.
        """
        official = _CountingProvider("official", _make_provider_test_snapshot(beatmapset_id=1000))
        mirror = _CountingProvider("mirror", None)

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        _ = await composite.lookup_by_beatmap_id(2000)

        assert official.last_called_method == "lookup_by_beatmap_id"

    async def test_lookup_by_beatmapset_id_delegates(self) -> None:
        """Beatmapset ID lookupが両sub-providerの同名methodへ委譲される契約を検証する.

        None officialとsnapshot mirrorでbeatmapset ID lookupを実行し,
        両providerのlast_called_methodを確認する.

        Returns:
            None: beatmapset ID delegationを検証して完了し, 呼び出し側へ値を返さない.
        """
        official = _CountingProvider("official", None)
        mirror = _CountingProvider("mirror", _make_provider_test_snapshot(beatmapset_id=1000))

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        _ = await composite.lookup_by_beatmapset_id(1000)

        assert official.last_called_method == "lookup_by_beatmapset_id"
        assert mirror.last_called_method == "lookup_by_beatmapset_id"

    async def test_lookup_by_checksum_delegates(self) -> None:
        """Checksum lookupが両sub-providerの同名methodへ委譲される契約を検証する.

        Noneを返す両providerでchecksum lookupを実行し, 両providerのlast_called_methodを確認する.

        Returns:
            None: checksum delegationを検証して完了し, 呼び出し側へ値を返さない.
        """
        official = _CountingProvider("official", None)
        mirror = _CountingProvider("mirror", None)

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        _ = await composite.lookup_by_checksum("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")

        assert official.last_called_method == "lookup_by_checksum"
        assert mirror.last_called_method == "lookup_by_checksum"


# ---------------------------------------------------------------------------
# BeatmapSourceError tests
# ---------------------------------------------------------------------------


class TestBeatmapSourceError:
    """BeatmapSourceErrorのcategoryとcontext field契約を検証する."""

    def test_configuration_category(self) -> None:
        """CONFIGURATION errorがcategoryとmessageを保持する契約を検証する.

        missing API key messageを持つconfiguration errorを生成する.
        categoryと文字列表現が入力と一致することを確認する.

        Returns:
            None: configuration error情報を検証して完了し, 呼び出し側へ値を返さない.
        """
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.CONFIGURATION,
            source="official",
            lookup_key="N/A",
            message="missing API key",
        )
        assert err.category is BeatmapSourceErrorCategory.CONFIGURATION
        assert "missing API key" in str(err)

    def test_unauthorized_category(self) -> None:
        """UNAUTHORIZED errorがcategoryを保持する契約を検証する.

        invalid credentials messageを持つunauthorized errorを生成する.
        categoryがUNAUTHORIZEDとなることを確認する.

        Returns:
            None: unauthorized categoryを検証して完了し, 呼び出し側へ値を返さない.
        """
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.UNAUTHORIZED,
            source="official",
            lookup_key="2000",
            message="invalid credentials",
        )
        assert err.category is BeatmapSourceErrorCategory.UNAUTHORIZED

    def test_rate_limited_category(self) -> None:
        """RATE_LIMITED errorがcategoryを保持する契約を検証する.

        rate limit messageを持つerrorを生成し, categoryがRATE_LIMITEDとなることを確認する.

        Returns:
            None: rate-limit categoryを検証して完了し, 呼び出し側へ値を返さない.
        """
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.RATE_LIMITED,
            source="official",
            lookup_key="2000",
            message="rate limit exceeded",
        )
        assert err.category is BeatmapSourceErrorCategory.RATE_LIMITED

    def test_timeout_category(self) -> None:
        """TIMEOUT errorがcategoryを保持する契約を検証する.

        request timed out messageを持つerrorを生成し, categoryがTIMEOUTとなることを確認する.

        Returns:
            None: timeout categoryを検証して完了し, 呼び出し側へ値を返さない.
        """
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.TIMEOUT,
            source="official",
            lookup_key="2000",
            message="request timed out",
        )
        assert err.category is BeatmapSourceErrorCategory.TIMEOUT

    def test_temporary_unavailable_category(self) -> None:
        """TEMPORARY_UNAVAILABLE errorがcategoryを保持する契約を検証する.

        503 messageを持つerrorを生成し, categoryがTEMPORARY_UNAVAILABLEとなることを確認する.

        Returns:
            None: temporary-unavailable categoryを検証して完了し, 呼び出し側へ値を返さない.
        """
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
            source="official",
            lookup_key="2000",
            message="503 Service Unavailable",
        )
        assert err.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE

    def test_not_found_category(self) -> None:
        """NOT_FOUND errorがcategoryを保持する契約を検証する.

        404 messageを持つerrorを生成し, categoryがNOT_FOUNDとなることを確認する.

        Returns:
            None: not-found categoryを検証して完了し, 呼び出し側へ値を返さない.
        """
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.NOT_FOUND,
            source="official",
            lookup_key="2000",
            message="404 Not Found",
        )
        assert err.category is BeatmapSourceErrorCategory.NOT_FOUND

    def test_invalid_response_category(self) -> None:
        """INVALID_RESPONSE errorがcategoryを保持する契約を検証する.

        unexpected JSON messageを持つerrorを生成し, categoryがINVALID_RESPONSEとなることを確認する.

        Returns:
            None: invalid-response categoryを検証して完了し, 呼び出し側へ値を返さない.
        """
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
            source="official",
            lookup_key="2000",
            message="unexpected JSON structure",
        )
        assert err.category is BeatmapSourceErrorCategory.INVALID_RESPONSE

    def test_carries_source_and_lookup_key(self) -> None:
        """BeatmapSourceErrorがsourceとlookup keyを保持する契約を検証する.

        mirror sourceとabc123 lookup keyを持つtimeout errorを生成する.
        両context fieldが入力と一致することを確認する.

        Returns:
            None: error context fieldを検証して完了し, 呼び出し側へ値を返さない.
        """
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.TIMEOUT,
            source="mirror",
            lookup_key="abc123",
            message="timed out",
        )
        assert err.source == "mirror"
        assert err.lookup_key == "abc123"

    def test_carries_original_exception(self) -> None:
        """BeatmapSourceErrorがoriginal exception instanceを保持する契約を検証する.

        ValueError instanceをoriginal_errorとして渡してerrorを生成する.
        同一instanceが保持されることを確認する.

        Returns:
            None: original exception保持を検証して完了し, 呼び出し側へ値を返さない.
        """
        original = ValueError("some underlying error")
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
            source="official",
            lookup_key="2000",
            message="parse failure",
            original_error=original,
        )
        assert err.original_error is original

    def test_original_error_defaults_to_none(self) -> None:
        """Original_error未指定のBeatmapSourceErrorがNoneを保持する契約を検証する.

        original exceptionなしでnot-found errorを生成する.
        original_error fieldがNoneとなることを確認する.

        Returns:
            None: optional original error既定値を検証して完了し, 呼び出し側へ値を返さない.
        """
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.NOT_FOUND,
            source="official",
            lookup_key="2000",
            message="not found",
        )
        assert err.original_error is None


# ---------------------------------------------------------------------------
# FakeBeatmapMetadataProvider Protocol compatibility
# ---------------------------------------------------------------------------


class TestFakeBeatmapMetadataProviderProtocol:
    """FactoryのFakeBeatmapMetadataProvider API契約を検証する."""

    def test_has_expected_method_names(self) -> None:
        """Fake providerが3種類のlookup methodを公開する契約を検証する.

        fake providerを生成してattributeを調べる.
        beatmap IDとset IDとchecksum用methodが全てあることを確認する.

        Returns:
            None: fake provider API surfaceを検証して完了し, 呼び出し側へ値を返さない.
        """
        fake = FakeBeatmapMetadataProvider()
        assert hasattr(fake, "lookup_by_beatmap_id")
        assert hasattr(fake, "lookup_by_beatmapset_id")
        assert hasattr(fake, "lookup_by_checksum")

    def test_methods_are_async(self) -> None:
        """Fake providerのlookup methodがcoroutine functionである契約を検証する.

        fake providerを生成して各methodをinspectする.
        全lookup methodがasyncとして検出されることを確認する.

        Returns:
            None: async lookup APIを検証して完了し, 呼び出し側へ値を返さない.
        """
        fake = FakeBeatmapMetadataProvider()
        assert inspect.iscoroutinefunction(fake.lookup_by_beatmap_id)
        assert inspect.iscoroutinefunction(fake.lookup_by_beatmapset_id)
        assert inspect.iscoroutinefunction(fake.lookup_by_checksum)

    def test_methods_accept_correct_parameters(self) -> None:
        """Fake providerのlookup methodがdomain key parameterを受ける契約を検証する.

        各lookup signatureをinspectする.
        beatmap_idとbeatmapset_idとchecksum_md5が含まれることを確認する.

        Returns:
            None: lookup parameter APIを検証して完了し, 呼び出し側へ値を返さない.
        """
        fake = FakeBeatmapMetadataProvider()
        sig_bid = inspect.signature(fake.lookup_by_beatmap_id)
        sig_bsid = inspect.signature(fake.lookup_by_beatmapset_id)
        sig_ck = inspect.signature(fake.lookup_by_checksum)

        assert "beatmap_id" in sig_bid.parameters
        assert "beatmapset_id" in sig_bsid.parameters
        assert "checksum_md5" in sig_ck.parameters

    def test_returns_response_with_snapshot_for_success(self) -> None:
        """Success responseを設定したfake providerがsnapshot responseを保持する契約を検証する.

        success metadata responseをbeatmap ID mapへ設定してfakeを生成する.
        map entryのkindがSUCCESSとなることを確認する.

        Returns:
            None: success response設定を検証して完了し, 呼び出し側へ値を返さない.
        """
        snap = make_metadata_provider_response(kind=FakeProviderResultKind.SUCCESS)
        fake = FakeBeatmapMetadataProvider(by_beatmap_id={2000: snap})
        assert 2000 in fake.by_beatmap_id
        assert fake.by_beatmap_id[2000].kind is FakeProviderResultKind.SUCCESS

    def test_default_response_is_not_found(self) -> None:
        """未設定keyのfake provider既定responseがNOT_FOUNDである契約を検証する.

        response mapなしでfakeを生成し, default_response kindがnot_foundとなることを確認する.

        Returns:
            None: default fake responseを検証して完了し, 呼び出し側へ値を返さない.
        """
        fake = FakeBeatmapMetadataProvider()
        assert fake.default_response.kind.value == "not_found"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider_test_snapshot(beatmapset_id: int = 1000) -> BeatmapsetSnapshot:
    """Provider test用の最小verified BeatmapsetSnapshotを生成する.

    Args:
        beatmapset_id (int): setとchild ID計算の基礎にする識別子.

    Returns:
        BeatmapsetSnapshot: official sourceと1件childを持つ固定metadata snapshot.
    """
    now = datetime.now(UTC)
    child = BeatmapSnapshot(
        beatmap_id=beatmapset_id * 2,
        beatmapset_id=beatmapset_id,
        checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        mode=BeatmapMode.OSU,
        version="Normal",
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        last_fetched_at=now,
    )
    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist="Test Artist",
        title="Test Title",
        creator="Test Creator",
        source=BeatmapMetadataSource.OFFICIAL,
        verified=BeatmapSourceVerification.VERIFIED,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(child,),
        last_fetched_at=now,
        next_refresh_at=now + timedelta(days=30),
    )


class _CountingProvider:
    """固定responseを返しlookup呼び出しを記録するprovider fakeを表す.

    Attributes:
        name (str): logやassertionでsourceを識別するprovider名.
        response (BeatmapsetSnapshot | None): 各lookupが返す固定snapshotまたはNone.
        lookup_by_beatmap_id_calls (int): beatmap ID lookupの呼び出し回数.
        lookup_by_beatmapset_id_calls (int): beatmapset ID lookupの呼び出し回数.
        lookup_by_checksum_calls (int): checksum lookupの呼び出し回数.
        last_called_method (str | None): 最後に実行したlookup method名. 未実行時はNone.
    """

    name: str
    response: BeatmapsetSnapshot | None
    lookup_by_beatmap_id_calls: int
    lookup_by_beatmapset_id_calls: int
    lookup_by_checksum_calls: int
    last_called_method: str | None

    def __init__(self, name: str, response: BeatmapsetSnapshot | None) -> None:
        """固定responseと空のlookup記録でprovider fakeを初期化する.

        Args:
            name (str): providerを区別するsource名.
            response (BeatmapsetSnapshot | None): 各lookupが返す固定結果.
        """
        self.name = name
        self.response = response
        self.lookup_by_beatmap_id_calls = 0
        self.lookup_by_beatmapset_id_calls = 0
        self.lookup_by_checksum_calls = 0
        self.last_called_method = None

    async def lookup_by_beatmap_id(
        self,
        beatmap_id: int,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> BeatmapsetSnapshot | None:
        """Beatmap ID lookupを記録して固定responseを返す.

        Args:
            beatmap_id (int): 呼び出し形を検証するbeatmap識別子.

        Returns:
            BeatmapsetSnapshot | None: 初期化時に設定した固定response.
        """
        self.lookup_by_beatmap_id_calls += 1
        self.last_called_method = "lookup_by_beatmap_id"
        return self.response

    async def lookup_by_beatmapset_id(
        self,
        beatmapset_id: int,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> BeatmapsetSnapshot | None:
        """Beatmapset ID lookupを記録して固定responseを返す.

        Args:
            beatmapset_id (int): 呼び出し形を検証するbeatmapset識別子.

        Returns:
            BeatmapsetSnapshot | None: 初期化時に設定した固定response.
        """
        self.lookup_by_beatmapset_id_calls += 1
        self.last_called_method = "lookup_by_beatmapset_id"
        return self.response

    async def lookup_by_checksum(
        self,
        checksum_md5: str,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> BeatmapsetSnapshot | None:
        """Checksum lookupを記録して固定responseを返す.

        Args:
            checksum_md5 (str): 呼び出し形を検証するbeatmap checksum.

        Returns:
            BeatmapsetSnapshot | None: 初期化時に設定した固定response.
        """
        self.lookup_by_checksum_calls += 1
        self.last_called_method = "lookup_by_checksum"
        return self.response


class _RaisingProvider:
    """各lookupで設定済みexceptionを送出するprovider fakeを表す.

    Attributes:
        name (str): error sourceを区別するprovider名.
        exception (Exception): 各lookupで送出するexception instance.
    """

    name: str
    exception: Exception

    def __init__(self, name: str, exception: Exception) -> None:
        """Source名と送出するexceptionでprovider fakeを初期化する.

        Args:
            name (str): error sourceを区別するprovider名.
            exception (Exception): 各lookupで再送出するexception instance.
        """
        self.name = name
        self.exception = exception

    async def lookup_by_beatmap_id(
        self,
        beatmap_id: int,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> BeatmapsetSnapshot | None:
        """Beatmap ID lookupを失敗させる.

        Args:
            beatmap_id (int): failure pathへ渡されるbeatmap識別子.
        """
        raise self.exception

    async def lookup_by_beatmapset_id(
        self,
        beatmapset_id: int,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> BeatmapsetSnapshot | None:
        """Beatmapset ID lookupを失敗させる.

        Args:
            beatmapset_id (int): failure pathへ渡されるbeatmapset識別子.
        """
        raise self.exception

    async def lookup_by_checksum(
        self,
        checksum_md5: str,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> BeatmapsetSnapshot | None:
        """Checksum lookupを失敗させる.

        Args:
            checksum_md5 (str): failure pathへ渡されるbeatmap checksum.
        """
        raise self.exception


def _make_null_provider() -> _CountingProvider:
    """常にNoneを返す名前付きCountingProviderを生成する.

    Returns:
        _CountingProvider: null source名とNone responseを持つprovider fake.
    """
    return _CountingProvider("null", None)
