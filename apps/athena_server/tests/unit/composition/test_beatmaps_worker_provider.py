"""Beatmap worker provider内のosu!direct catalog adapter契約を検証する."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from osu_server.composition.providers.beatmaps_worker import DirectCatalogFetcher
from osu_server.domain.beatmaps import (
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
    DirectCoverageStatusScope,
)
from osu_server.services.commands.beatmaps.direct_catalog_sync import DirectRangeCrawlChunk

if TYPE_CHECKING:
    from osu_server.infrastructure.beatmaps import OsuApiMetadataProviderService

_NOW = datetime(2026, 8, 15, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)


class RecordingMetadataProvider:
    """BeatmapSet ID lookupのroutingを記録するmetadata provider fake.

    Attributes:
        snapshots_by_beatmapset_id (dict[int, BeatmapsetSnapshot]): 返却するsnapshot.
        beatmapset_lookup_ids (list[int]): lookup_by_beatmapset_idが受け取ったID列.
    """

    snapshots_by_beatmapset_id: dict[int, BeatmapsetSnapshot]
    beatmapset_lookup_ids: list[int]

    def __init__(self, snapshots: tuple[BeatmapsetSnapshot, ...] = ()) -> None:
        """固定snapshot列をBeatmapSet ID lookup用に保持する.

        Args:
            snapshots (tuple[BeatmapsetSnapshot, ...]): lookupで返すsnapshot列.
        """
        self.snapshots_by_beatmapset_id = {
            snapshot.beatmapset_id: snapshot for snapshot in snapshots
        }
        self.beatmapset_lookup_ids = []

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        """Beatmap ID lookupはこのtest doubleで未使用のためNoneを返す.

        Args:
            beatmap_id (int): 呼び出し側が指定したBeatmap ID.

        Returns:
            BeatmapsetSnapshot | None: 常にNone.
        """
        _ = beatmap_id
        return None

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        """BeatmapSet ID lookupを記録し固定snapshotを返す.

        Args:
            beatmapset_id (int): lookup対象のBeatmapSet ID.

        Returns:
            BeatmapsetSnapshot | None: IDに対応するsnapshot. 未登録ならNone.
        """
        self.beatmapset_lookup_ids.append(beatmapset_id)
        return self.snapshots_by_beatmapset_id.get(beatmapset_id)

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        """Checksum lookupはこのtest doubleで未使用のためNoneを返す.

        Args:
            checksum_md5 (str): 呼び出し側が指定したchecksum.

        Returns:
            BeatmapsetSnapshot | None: 常にNone.
        """
        _ = checksum_md5
        return None


@pytest.mark.asyncio
async def test_direct_catalog_fetcher_routes_mirror_range_to_mirror_provider() -> None:
    """Mirror sourceのrange crawlがmirror providerとfallback budgetを使うことを検証する.

    Returns:
        None: mirror providerだけが呼ばれ, request countがbase URL数で補正されることを確認する.
    """
    mirror_snapshot = _snapshot(10, source=BeatmapMetadataSource.MIRROR)
    mirror_provider = RecordingMetadataProvider((mirror_snapshot,))
    official_provider = RecordingMetadataProvider()
    fetcher = DirectCatalogFetcher(
        official_provider=cast("OsuApiMetadataProviderService", cast("object", official_provider)),
        mirror_provider=mirror_provider,
        mirror_lookup_request_count=3,
    )
    chunk = _chunk(source=BeatmapMetadataSource.MIRROR, from_beatmapset_id=10, to_beatmapset_id=11)

    result = await fetcher.fetch_id_range(chunk)

    assert result.beatmapsets == (mirror_snapshot,)
    assert mirror_provider.beatmapset_lookup_ids == [10, 11]
    assert official_provider.beatmapset_lookup_ids == []
    assert fetcher.request_count_for_chunk(chunk) == 6


@pytest.mark.asyncio
async def test_direct_catalog_fetcher_routes_official_range_to_official_provider() -> None:
    """Official sourceのrange crawlがofficial providerとtoken予算を使うことを検証する.

    Returns:
        None: official providerだけが呼ばれ, request countがtoken分を含むことを確認する.
    """
    official_snapshot = _snapshot(20, source=BeatmapMetadataSource.OFFICIAL)
    mirror_provider = RecordingMetadataProvider()
    official_provider = RecordingMetadataProvider((official_snapshot,))
    fetcher = DirectCatalogFetcher(
        official_provider=cast("OsuApiMetadataProviderService", cast("object", official_provider)),
        mirror_provider=mirror_provider,
        mirror_lookup_request_count=3,
    )
    chunk = _chunk(
        source=BeatmapMetadataSource.OFFICIAL, from_beatmapset_id=20, to_beatmapset_id=21
    )

    result = await fetcher.fetch_id_range(chunk)

    assert result.beatmapsets == (official_snapshot,)
    assert official_provider.beatmapset_lookup_ids == [20, 21]
    assert mirror_provider.beatmapset_lookup_ids == []
    assert fetcher.request_count_for_chunk(chunk) == 3


@pytest.mark.asyncio
async def test_direct_catalog_fetcher_rejects_mirror_range_when_mirror_source_missing() -> None:
    """Mirror source未設定時のrange crawlが明示的に失敗することを検証する.

    Returns:
        None: request count算出とfetchの両方がRuntimeErrorになることを確認する.
    """
    mirror_provider = RecordingMetadataProvider()
    fetcher = DirectCatalogFetcher(
        official_provider=None,
        mirror_provider=mirror_provider,
        mirror_lookup_request_count=0,
    )
    chunk = _chunk(source=BeatmapMetadataSource.MIRROR, from_beatmapset_id=10, to_beatmapset_id=11)

    with pytest.raises(RuntimeError, match="mirror metadata source is not configured"):
        _ = fetcher.request_count_for_chunk(chunk)
    with pytest.raises(RuntimeError, match="mirror metadata source is not configured"):
        _ = await fetcher.fetch_id_range(chunk)
    assert mirror_provider.beatmapset_lookup_ids == []


@pytest.mark.asyncio
async def test_direct_catalog_fetcher_rejects_official_range_when_official_provider_missing() -> (
    None
):
    """Official source未設定時のrange crawlが明示的に失敗することを検証する.

    Returns:
        None: official providerなしのsource指定がRuntimeErrorになることを確認する.
    """
    fetcher = DirectCatalogFetcher(
        official_provider=None,
        mirror_provider=RecordingMetadataProvider(),
    )

    with pytest.raises(RuntimeError, match="official metadata source is not configured"):
        _ = await fetcher.fetch_id_range(
            _chunk(
                source=BeatmapMetadataSource.OFFICIAL,
                from_beatmapset_id=20,
                to_beatmapset_id=20,
            )
        )


def _chunk(
    *,
    source: BeatmapMetadataSource,
    from_beatmapset_id: int,
    to_beatmapset_id: int,
) -> DirectRangeCrawlChunk:
    """Range crawl test用chunkを構築する.

    Args:
        source (BeatmapMetadataSource): route対象のmetadata source.
        from_beatmapset_id (int): range開始ID.
        to_beatmapset_id (int): range終了ID.

    Returns:
        DirectRangeCrawlChunk: ranked scopeのrange crawl chunk.
    """
    return DirectRangeCrawlChunk(
        source=source,
        status_scope=DirectCoverageStatusScope.RANKED,
        from_beatmapset_id=from_beatmapset_id,
        to_beatmapset_id=to_beatmapset_id,
    )


def _snapshot(
    beatmapset_id: int,
    *,
    source: BeatmapMetadataSource,
) -> BeatmapsetSnapshot:
    """Catalog fetcher test用snapshotを構築する.

    Args:
        beatmapset_id (int): snapshotのBeatmapSet ID.
        source (BeatmapMetadataSource): snapshotのmetadata source.

    Returns:
        BeatmapsetSnapshot: 単一childを持つsnapshot.
    """
    beatmap_id = beatmapset_id + 100_000
    beatmap = BeatmapSnapshot(
        beatmap_id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=f"{beatmap_id:032x}",
        mode=BeatmapMode.OSU,
        version=f"Difficulty {beatmapset_id}",
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=source,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
        official_last_updated_at=_NOW,
    )
    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist=f"Artist {beatmapset_id}",
        title=f"Title {beatmapset_id}",
        creator="Mapper",
        source=source,
        verified=BeatmapSourceVerification.VERIFIED,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=source,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )
