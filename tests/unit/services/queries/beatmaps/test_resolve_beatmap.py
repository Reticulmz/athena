"""Unit tests for beatmap resolution query use-case."""

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
)
from osu_server.services.queries.beatmaps.resolve_beatmap import (
    ResolveBeatmapByChecksumQuery,
    ResolveBeatmapByIdQuery,
)


class BeatmapQueryRepositoryStub:
    """Typed test double for the read-only beatmap query repository."""

    def __init__(self) -> None:
        self.beatmaps_by_id: dict[int, Beatmap] = {}
        self.beatmapsets_by_id: dict[int, BeatmapSet] = {}
        self.beatmap_id_by_checksum: dict[str, int] = {}
        self.attachments_by_beatmap_id: dict[int, BeatmapFileAttachment] = {}
        self.fetch_states_by_target: dict[BeatmapFetchTarget, BeatmapFetchRecord] = {}

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        return self.beatmaps_by_id.get(beatmap_id)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        return self.beatmapsets_by_id.get(beatmapset_id)

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        beatmap_id = self.beatmap_id_by_checksum.get(checksum_md5)
        if beatmap_id is None:
            return None
        return self.beatmaps_by_id.get(beatmap_id)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        beatmapset = self.beatmapsets_by_id.get(beatmapset_id)
        if beatmapset is None:
            return None
        for beatmap in beatmapset.beatmaps:
            attachment = beatmap.file_attachment
            if attachment is not None and attachment.original_filename == original_filename:
                return beatmap
        return None

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        return self.attachments_by_beatmap_id.get(beatmap_id)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        return self.fetch_states_by_target.get(target)


@pytest.fixture
def beatmap_query_repo() -> BeatmapQueryRepositoryStub:
    """Typed beatmap query repository stub."""
    return BeatmapQueryRepositoryStub()


@pytest.fixture
def sample_beatmap() -> Beatmap:
    """Sample beatmap for testing."""
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
    """Sample beatmapset for testing."""
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
    """Tests for resolve beatmap by ID query use-case."""

    async def test_returns_none_when_beatmap_not_found(
        self, beatmap_query_repo: BeatmapQueryRepositoryStub
    ) -> None:
        """Query returns None when beatmap doesn't exist."""
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
        """Query returns beatmap and beatmapset when they exist."""
        beatmap_query_repo.beatmaps_by_id[sample_beatmap.id] = sample_beatmap
        beatmap_query_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        query = ResolveBeatmapByIdQuery(beatmap_query_repo)
        result = await query.execute(beatmap_id=123, options=None)

        assert result.beatmap == sample_beatmap
        assert result.beatmapset == sample_beatmapset
        assert result.metadata_status == BeatmapFetchState.FRESH


class TestResolveBeatmapByChecksumQuery:
    """Tests for resolve beatmap by checksum query use-case."""

    async def test_returns_none_when_beatmap_not_found_by_checksum(
        self, beatmap_query_repo: BeatmapQueryRepositoryStub
    ) -> None:
        """Query returns None when beatmap with checksum doesn't exist."""
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
        """Query returns beatmap when found by checksum."""
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
        """Query returns explicit unavailable result structure."""
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
        """Query returns stored fetch state instead of mutating to fill read data."""
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
