"""Unit tests for legacy getscores query use-case."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchRecord,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.compatibility.stable.getscores import (
    GetscoresOutcomeKind,
    GetscoresRequest,
    GetscoresResolveReason,
)
from osu_server.domain.scores.score import Ruleset
from osu_server.services.queries.scores.beatmap_leaderboards import BeatmapLeaderboardQuery
from osu_server.services.queries.scores.beatmap_score_listing import BeatmapScoreListingQuery
from osu_server.transports.stable.web_legacy.mappers import StableGetscoresLeaderboardMapper

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
        BeatmapLeaderboardRow,
        LeaderboardReadScope,
    )


class BeatmapScoreListingQueryRepositoryStub:
    """Typed read-only getscores repository test double."""

    def __init__(self) -> None:
        self.beatmaps_by_checksum: dict[str, Beatmap] = {}
        self.beatmaps_by_filename: dict[tuple[int, str], Beatmap] = {}
        self.beatmapsets_by_id: dict[int, BeatmapSet] = {}
        self.fetch_records: dict[BeatmapFetchTarget, BeatmapFetchRecord] = {}

    async def find_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        return self.beatmaps_by_checksum.get(checksum_md5)

    async def find_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        return self.beatmaps_by_filename.get((beatmapset_id, original_filename))

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        return self.beatmapsets_by_id.get(beatmapset_id)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        return self.fetch_records.get(target)


class EmptyBeatmapLeaderboardQueryRepositoryStub:
    """Typed empty leaderboard repository test double."""

    def __init__(self) -> None:
        self.top_row_calls: list[tuple[LeaderboardReadScope, int]] = []
        self.personal_best_calls: list[tuple[LeaderboardReadScope, int]] = []

    async def list_top_rows(
        self,
        scope: LeaderboardReadScope,
        *,
        limit: int,
    ) -> tuple[BeatmapLeaderboardRow, ...]:
        self.top_row_calls.append((scope, limit))
        return ()

    async def get_personal_best(
        self,
        scope: LeaderboardReadScope,
        *,
        viewer_user_id: int,
    ) -> BeatmapLeaderboardRow | None:
        self.personal_best_calls.append((scope, viewer_user_id))
        return None


def _with_leaderboard_selection(request: GetscoresRequest) -> GetscoresRequest:
    return replace(
        request,
        leaderboard_selection=StableGetscoresLeaderboardMapper().map_request(request),
    )


@pytest.fixture
def getscores_repo() -> BeatmapScoreListingQueryRepositoryStub:
    """Typed getscores query repository stub."""
    return BeatmapScoreListingQueryRepositoryStub()


@pytest.fixture
def leaderboard_repo() -> EmptyBeatmapLeaderboardQueryRepositoryStub:
    """Typed leaderboard query repository stub."""
    return EmptyBeatmapLeaderboardQueryRepositoryStub()


def _query(
    getscores_repo: BeatmapScoreListingQueryRepositoryStub,
    leaderboard_repo: EmptyBeatmapLeaderboardQueryRepositoryStub,
) -> BeatmapScoreListingQuery:
    return BeatmapScoreListingQuery(BeatmapLeaderboardQuery(getscores_repo, leaderboard_repo))


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


class TestBeatmapScoreListingQuery:
    """Tests for legacy getscores query use-case."""

    async def test_returns_unavailable_when_beatmap_not_found_by_checksum(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: EmptyBeatmapLeaderboardQueryRepositoryStub,
    ) -> None:
        """Query returns unavailable when beatmap not found."""
        query = _query(getscores_repo, leaderboard_repo)
        result = await query.resolve_by_checksum(checksum_md5="a" * 32)

        assert result.kind == GetscoresOutcomeKind.UNAVAILABLE
        assert result.header is None
        assert result.reason == GetscoresResolveReason.NOT_FOUND

    async def test_returns_header_when_beatmap_found_by_checksum(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: EmptyBeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        """Query returns header when beatmap is found."""
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        query = _query(getscores_repo, leaderboard_repo)
        result = await query.resolve_by_checksum(checksum_md5="a" * 32)

        assert result.kind == GetscoresOutcomeKind.HEADER
        assert result.header is not None
        assert result.header.beatmap == sample_beatmap
        assert result.header.beatmapset == sample_beatmapset
        assert result.reason == GetscoresResolveReason.KNOWN_CHECKSUM

    async def test_returns_unavailable_when_beatmapset_not_found(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: EmptyBeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
    ) -> None:
        """Query returns unavailable when beatmapset is missing."""
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap

        query = _query(getscores_repo, leaderboard_repo)
        result = await query.resolve_by_checksum(checksum_md5="a" * 32)

        assert result.kind == GetscoresOutcomeKind.UNAVAILABLE
        assert result.header is None
        assert result.reason == GetscoresResolveReason.NOT_FOUND

    async def test_returns_unavailable_for_not_submitted_status(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: EmptyBeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        """Query returns unavailable for NOT_SUBMITTED status."""
        # Create beatmap with NOT_SUBMITTED status
        not_submitted_beatmap = Beatmap(
            id=sample_beatmap.id,
            beatmapset_id=sample_beatmap.beatmapset_id,
            checksum_md5=sample_beatmap.checksum_md5,
            mode=sample_beatmap.mode,
            version=sample_beatmap.version,
            total_length=sample_beatmap.total_length,
            hit_length=sample_beatmap.hit_length,
            max_combo=sample_beatmap.max_combo,
            bpm=sample_beatmap.bpm,
            cs=sample_beatmap.cs,
            od=sample_beatmap.od,
            ar=sample_beatmap.ar,
            hp=sample_beatmap.hp,
            difficulty_rating=sample_beatmap.difficulty_rating,
            official_status=BeatmapRankStatus.NOT_SUBMITTED,
            official_status_source=sample_beatmap.official_status_source,
            official_status_verified=sample_beatmap.official_status_verified,
            local_status_override=sample_beatmap.local_status_override,
            metadata_fetch_state=sample_beatmap.metadata_fetch_state,
            file_state=sample_beatmap.file_state,
            file_attachment=sample_beatmap.file_attachment,
            last_fetched_at=sample_beatmap.last_fetched_at,
            next_refresh_at=sample_beatmap.next_refresh_at,
        )

        getscores_repo.beatmaps_by_checksum[not_submitted_beatmap.checksum_md5] = (
            not_submitted_beatmap
        )
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        query = _query(getscores_repo, leaderboard_repo)
        result = await query.resolve_by_checksum(checksum_md5="a" * 32)

        assert result.kind == GetscoresOutcomeKind.UNAVAILABLE
        assert result.header is None
        assert result.reason == GetscoresResolveReason.NOT_SUBMITTED

    async def test_resolve_returns_update_available_for_checksum_miss_with_filename_match(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: EmptyBeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        """Parsed request query preserves stable update-available behavior read-only."""
        filename = "Artist - Title (Creator) [Normal].osu"
        getscores_repo.beatmaps_by_filename[(sample_beatmap.beatmapset_id, filename)] = (
            sample_beatmap
        )
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        query = _query(getscores_repo, leaderboard_repo)
        result = await query.resolve(
            GetscoresRequest(
                checksum_md5="b" * 32,
                filename=filename,
                beatmapset_id_hint=sample_beatmap.beatmapset_id,
                mode=None,
                mods=None,
                leaderboard_type=None,
                leaderboard_version=None,
                song_select=None,
            )
        )

        assert result.kind == GetscoresOutcomeKind.UPDATE_AVAILABLE
        assert result.header is not None
        assert result.header.beatmap == sample_beatmap
        assert result.reason == GetscoresResolveReason.UPDATE_AVAILABLE

    async def test_resolve_does_not_use_legacy_personal_best_fallback(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: EmptyBeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        query = _query(getscores_repo, leaderboard_repo)
        result = await query.resolve(
            _with_leaderboard_selection(
                GetscoresRequest(
                    checksum_md5=sample_beatmap.checksum_md5,
                    filename=None,
                    beatmapset_id_hint=None,
                    mode=Ruleset.OSU.value,
                    mods=0,
                    leaderboard_type=1,
                    leaderboard_version=4,
                    song_select=False,
                )
            ),
            user_id=9,
        )

        assert result.kind == GetscoresOutcomeKind.HEADER
        assert result.header is not None
        assert result.header.personal_best is None
        assert len(leaderboard_repo.top_row_calls) == 1
        scope, limit = leaderboard_repo.top_row_calls[0]
        assert scope.beatmap_id == sample_beatmap.id
        assert scope.category.name == "GLOBAL"
        assert limit == 50
        assert leaderboard_repo.personal_best_calls == []

    async def test_resolve_skips_personal_best_for_song_select(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: EmptyBeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        query = _query(getscores_repo, leaderboard_repo)
        result = await query.resolve(
            _with_leaderboard_selection(
                GetscoresRequest(
                    checksum_md5=sample_beatmap.checksum_md5,
                    filename=None,
                    beatmapset_id_hint=None,
                    mode=Ruleset.OSU.value,
                    mods=0,
                    leaderboard_type=1,
                    leaderboard_version=4,
                    song_select=True,
                )
            ),
            user_id=9,
        )

        assert result.kind == GetscoresOutcomeKind.HEADER
        assert result.header is not None
        assert result.header.personal_best is None
        assert leaderboard_repo.top_row_calls == []
        assert leaderboard_repo.personal_best_calls == []
