"""beatmap解決queryのunit testを定義する."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchRecord,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileAttachment,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
    DirectCoverageRecord,
    DirectCoverageStatusScope,
)
from osu_server.services.queries.beatmaps.resolve_beatmap import (
    ResolveBeatmapByChecksumQuery,
    ResolveBeatmapByIdQuery,
)


class BeatmapQueryRepositoryStub:
    """read-only beatmap query repositoryのtyped test doubleを提供する.

    Attributes:
        beatmaps_by_id (dict[int, Beatmap]): beatmap IDで参照するbeatmap.
        beatmapsets_by_id (dict[int, BeatmapSet]): beatmapset IDで参照するbeatmapset.
        beatmap_id_by_checksum (dict[str, int]): MD5 checksumから解決するbeatmap ID.
        attachments_by_beatmap_id (dict[int, BeatmapFileAttachment]): beatmap IDに対応する
            file attachment.
        fetch_states_by_target (dict[BeatmapFetchTarget, BeatmapFetchRecord]): 取得対象ごとの
            保存済みfetch state.
    """

    def __init__(self) -> None:
        """空のread modelを持つrepository stubを初期化する."""
        self.beatmaps_by_id: dict[int, Beatmap] = {}
        self.beatmapsets_by_id: dict[int, BeatmapSet] = {}
        self.beatmap_id_by_checksum: dict[str, int] = {}
        self.attachments_by_beatmap_id: dict[int, BeatmapFileAttachment] = {}
        self.fetch_states_by_target: dict[BeatmapFetchTarget, BeatmapFetchRecord] = {}

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        """Beatmap IDに一致する保存済みbeatmapを返す.

        Args:
            beatmap_id (int): 検索するbeatmapの識別子.

        Returns:
            Beatmap | None: 一致するbeatmap. 未登録の場合はNone.
        """
        return self.beatmaps_by_id.get(beatmap_id)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """Beatmapset IDに一致する保存済みbeatmapsetを返す.

        Args:
            beatmapset_id (int): 検索するbeatmapsetの識別子.

        Returns:
            BeatmapSet | None: 一致するbeatmapset. 未登録の場合はNone.
        """
        return self.beatmapsets_by_id.get(beatmapset_id)

    async def list_beatmapsets_by_ids(
        self,
        beatmapset_ids: tuple[int, ...],
    ) -> tuple[BeatmapSet, ...]:
        """Beatmapset ID列に一致する保存済みbeatmapsetを入力順で返す.

        Args:
            beatmapset_ids (tuple[int, ...]): 検索するbeatmapset ID列.

        Returns:
            tuple[BeatmapSet, ...]: 登録済みbeatmapsetだけを入力順で含む列.
        """
        return tuple(
            beatmapset
            for beatmapset_id in beatmapset_ids
            if (beatmapset := self.beatmapsets_by_id.get(beatmapset_id)) is not None
        )

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """MD5 checksumに一致する保存済みbeatmapを返す.

        Args:
            checksum_md5 (str): 検索するbeatmap fileのMD5 checksum.

        Returns:
            Beatmap | None: checksumに対応するbeatmap. 未登録の場合はNone.
        """
        beatmap_id = self.beatmap_id_by_checksum.get(checksum_md5)
        if beatmap_id is None:
            return None
        return self.beatmaps_by_id.get(beatmap_id)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """beatmapset内で元file名に一致するbeatmapを返す.

        Args:
            beatmapset_id (int): 検索対象のbeatmapset識別子.
            original_filename (str): 一致を確認する元のfile名.

        Returns:
            Beatmap | None: file attachmentの元file名が一致するbeatmap. 見つからない場合はNone.
        """
        beatmapset = self.beatmapsets_by_id.get(beatmapset_id)
        if beatmapset is None:
            return None
        for beatmap in beatmapset.beatmaps:
            attachment = beatmap.file_attachment
            if attachment is not None and attachment.original_filename == original_filename:
                return beatmap
        return None

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        """Beatmap IDに対応する現在のfile attachmentを返す.

        Args:
            beatmap_id (int): file attachmentを検索するbeatmapの識別子.

        Returns:
            BeatmapFileAttachment | None: 保存済みの現在のfile attachment. 未登録の場合はNone.
        """
        return self.attachments_by_beatmap_id.get(beatmap_id)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """取得対象に対応する保存済みfetch stateを返す.

        Args:
            target (BeatmapFetchTarget): 状態を検索する取得対象.

        Returns:
            BeatmapFetchRecord | None: 保存済みfetch state. 未登録の場合はNone.
        """
        return self.fetch_states_by_target.get(target)

    async def list_completed_direct_search_coverages(
        self,
        status_scopes: tuple[DirectCoverageStatusScope, ...],
        *,
        feed_sort_key: str,
        feed_window_key: str,
    ) -> tuple[DirectCoverageRecord, ...]:
        """Resolve queryでは使わないdirect検索coverageを空として返す.

        Args:
            status_scopes (tuple[DirectCoverageStatusScope, ...]): 未使用のstatus scope列.
            feed_sort_key (str): 未使用のfeed sort key.
            feed_window_key (str): 未使用のfeed window key.

        Returns:
            tuple[DirectCoverageRecord, ...]: このstubでは常に空tuple.
        """
        _ = status_scopes, feed_sort_key, feed_window_key
        return ()


@pytest.fixture
def beatmap_query_repo() -> BeatmapQueryRepositoryStub:
    """空のbeatmap query repository fixtureを提供する.

    Returns:
        BeatmapQueryRepositoryStub: testごとに独立した空のread model.
    """
    return BeatmapQueryRepositoryStub()


@pytest.fixture
def sample_beatmap() -> Beatmap:
    """解決成功契約に使うranked beatmap fixtureを提供する.

    Returns:
        Beatmap: attachmentを持たずfresh metadataを持つbeatmap.
    """
    return Beatmap(
        id=123,
        beatmapset_id=456,
        checksum_md5="a" * 32,
        mode=BeatmapMode.OSU,
        version="Normal",
        total_length=120,
        hit_length=100,
        max_combo=500,
        bpm=180.0,
        cs=4.0,
        od=8.0,
        ar=9.0,
        hp=6.0,
        difficulty_rating=5.5,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.AVAILABLE,
        file_attachment=None,
        last_fetched_at=datetime.now(UTC),
        next_refresh_at=None,
    )


@pytest.fixture
def sample_beatmapset() -> BeatmapSet:
    """解決成功契約に使うranked beatmapset fixtureを提供する.

    Returns:
        BeatmapSet: 空のbeatmap一覧を持つbeatmapset.
    """
    return BeatmapSet(
        id=456,
        artist="Test Artist",
        title="Test Title",
        creator="Test Creator",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(),
        last_fetched_at=datetime.now(UTC),
        next_refresh_at=None,
    )


class TestResolveBeatmapByIdQuery:
    """IDによるbeatmap解決queryのread contractを検証する."""

    async def test_returns_none_when_beatmap_not_found(
        self, beatmap_query_repo: BeatmapQueryRepositoryStub
    ) -> None:
        """存在しないbeatmap IDのunavailable結果を検証する.

        空のrepositoryで解決queryを実行し,beatmapとbeatmapsetがともにNoneのまま返ることを確認する.

        Args:
            beatmap_query_repo (BeatmapQueryRepositoryStub): 空のbeatmap read model fixture.

        Returns:
            None: unavailable結果の公開fieldを検証して完了する.
        """
        query = ResolveBeatmapByIdQuery(beatmap_query_repo)
        result = await query.execute(beatmap_id=999, options=None)

        assert result.beatmap is None
        assert result.beatmapset is None

    async def test_returns_beatmap_and_beatmapset_when_found(
        self,
        beatmap_query_repo: BeatmapQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        """保存済みbeatmap IDの解決結果とmetadata stateを検証する.

        beatmapとbeatmapsetをrepositoryへ登録してqueryを実行し,両方のobjectとfresh metadata
        stateが返ることを確認する.

        Args:
            beatmap_query_repo (BeatmapQueryRepositoryStub): 保存済みobjectを登録するbeatmap
                read model fixture.
            sample_beatmap (Beatmap): 解決対象として登録するbeatmap fixture.
            sample_beatmapset (BeatmapSet): beatmapに対応して登録するbeatmapset fixture.

        Returns:
            None: 解決結果とmetadata stateを検証して完了する.
        """
        beatmap_query_repo.beatmaps_by_id[sample_beatmap.id] = sample_beatmap
        beatmap_query_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        query = ResolveBeatmapByIdQuery(beatmap_query_repo)
        result = await query.execute(beatmap_id=123, options=None)

        assert result.beatmap == sample_beatmap
        assert result.beatmapset == sample_beatmapset
        assert result.metadata_status == BeatmapFetchState.FRESH


class TestResolveBeatmapByChecksumQuery:
    """MD5 checksumによるbeatmap解決queryのread contractを検証する."""

    async def test_returns_none_when_beatmap_not_found_by_checksum(
        self, beatmap_query_repo: BeatmapQueryRepositoryStub
    ) -> None:
        """未登録MD5 checksumのunavailable結果を検証する.

        空のrepositoryでqueryを実行し,beatmapとbeatmapsetがともにNoneのまま返ることを確認する.

        Args:
            beatmap_query_repo (BeatmapQueryRepositoryStub): checksum対応付けを持たない
                beatmap read model fixture.

        Returns:
            None: unavailable結果の公開fieldを検証して完了する.
        """
        query = ResolveBeatmapByChecksumQuery(beatmap_query_repo)
        result = await query.execute(checksum_md5="nonexistent", options=None)

        assert result.beatmap is None
        assert result.beatmapset is None

    async def test_returns_beatmap_when_found_by_checksum(
        self,
        beatmap_query_repo: BeatmapQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        """保存済みMD5 checksumがbeatmapとbeatmapsetへ解決されることを検証する.

        checksum対応付けと保存済みobjectを登録してqueryを実行し,対応するbeatmapとbeatmapsetが返ることを確認する.

        Args:
            beatmap_query_repo (BeatmapQueryRepositoryStub): checksum対応付けとobjectを登録する
                beatmap read model fixture.
            sample_beatmap (Beatmap): checksumから解決するbeatmap fixture.
            sample_beatmapset (BeatmapSet): 解決結果に含めるbeatmapset fixture.

        Returns:
            None: checksum解決結果を検証して完了する.
        """
        beatmap_query_repo.beatmaps_by_id[sample_beatmap.id] = sample_beatmap
        beatmap_query_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset
        beatmap_query_repo.beatmap_id_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap.id

        query = ResolveBeatmapByChecksumQuery(beatmap_query_repo)
        result = await query.execute(checksum_md5=sample_beatmap.checksum_md5, options=None)

        assert result.beatmap == sample_beatmap
        assert result.beatmapset == sample_beatmapset

    async def test_explicit_unavailable_result_when_not_found(
        self,
        beatmap_query_repo: BeatmapQueryRepositoryStub,
    ) -> None:
        """未登録MD5 checksumの明示的なpending fetch結果を検証する.

        fetch stateを持たないrepositoryでqueryを実行し,read dataを補完せずpending fetch
        stateを返すことを確認する.

        Args:
            beatmap_query_repo (BeatmapQueryRepositoryStub): fetch stateを持たないbeatmap read
                model fixture.

        Returns:
            None: unavailable結果の構造とpending stateを検証して完了する.
        """
        query = ResolveBeatmapByChecksumQuery(beatmap_query_repo)
        result = await query.execute(checksum_md5="missing", options=None)

        # Explicit unavailable structure
        assert result.beatmap is None
        assert result.beatmapset is None
        assert result.metadata_status == BeatmapFetchState.PENDING_FETCH

    async def test_unavailable_result_reflects_existing_fetch_state(
        self,
        beatmap_query_repo: BeatmapQueryRepositoryStub,
    ) -> None:
        """保存済みfetch stateをread dataの補完なしで反映することを検証する.

        failed fetch recordを登録してqueryを実行し,beatmapを作成せず保存済みfailed stateを
        返すことを確認する.

        Args:
            beatmap_query_repo (BeatmapQueryRepositoryStub): failed fetch recordを登録する
                beatmap read model fixture.

        Returns:
            None: 非mutatingなunavailable結果を検証して完了する.
        """
        target = BeatmapFetchTarget.metadata_by_checksum("missing")
        beatmap_query_repo.fetch_states_by_target[target] = BeatmapFetchRecord(
            target=target,
            status=BeatmapFetchState.FAILED,
            attempt_count=1,
            last_error="not found",
            pending_since=None,
            last_attempted_at=datetime.now(UTC),
        )

        query = ResolveBeatmapByChecksumQuery(beatmap_query_repo)
        result = await query.execute(checksum_md5="missing", options=None)

        assert result.beatmap is None
        assert result.beatmapset is None
        assert result.metadata_status == BeatmapFetchState.FAILED
