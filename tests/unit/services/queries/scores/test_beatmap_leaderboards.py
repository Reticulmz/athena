"""Beatmap leaderboard query integration tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchRecord,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.users import User
from osu_server.domain.scores.leaderboards import filter_from_mod_combination
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.personal_best import LeaderboardCategory
from osu_server.domain.scores.score import Playstyle, Ruleset
from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
    BeatmapLeaderboardRow,
    LeaderboardReadScope,
    ScoreHitCounts,
)
from osu_server.services.queries.scores.beatmap_leaderboards import (
    BeatmapLeaderboardOutcomeKind,
    BeatmapLeaderboardQuery,
    BeatmapLeaderboardRequest,
    BeatmapLeaderboardResolveReason,
    BeatmapLeaderboardResult,
)

_NOW = datetime(2026, 6, 18, tzinfo=UTC)
_CHECKSUM = "a" * 32
_OLD_CHECKSUM = "b" * 32
_FILENAME = "Artist - Title (Creator) [Insane].osu"


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


class BeatmapLeaderboardQueryRepositoryStub:
    """Typed leaderboard repository test double for query-level guard tests."""

    def __init__(self) -> None:
        self.rows: tuple[BeatmapLeaderboardRow, ...] = ()
        self.personal_best: BeatmapLeaderboardRow | None = None
        self.top_row_calls: list[tuple[LeaderboardReadScope, int]] = []
        self.personal_best_calls: list[tuple[LeaderboardReadScope, int]] = []

    async def list_top_rows(
        self,
        scope: LeaderboardReadScope,
        *,
        limit: int,
    ) -> tuple[BeatmapLeaderboardRow, ...]:
        self.top_row_calls.append((scope, limit))
        return self.rows

    async def get_personal_best(
        self,
        scope: LeaderboardReadScope,
        *,
        viewer_user_id: int,
    ) -> BeatmapLeaderboardRow | None:
        self.personal_best_calls.append((scope, viewer_user_id))
        return self.personal_best


class ViewerUserQueryRepositoryStub:
    """Typed user repository test double for viewer context resolution."""

    def __init__(self) -> None:
        self.users_by_id: dict[int, User] = {}
        self.calls: list[int] = []
        self.safe_username_calls: list[str] = []
        self.email_calls: list[str] = []
        self.username_disallowed_calls: list[str] = []

    async def get_by_id(self, user_id: int) -> User | None:
        self.calls.append(user_id)
        return self.users_by_id.get(user_id)

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        self.safe_username_calls.append(safe_username)
        return None

    async def get_by_email(self, email: str) -> User | None:
        self.email_calls.append(email)
        return None

    async def is_username_disallowed(self, safe_username: str) -> bool:
        self.username_disallowed_calls.append(safe_username)
        return False


class ViewerPermissionServiceStub:
    """Typed permission service test double for viewer visibility checks."""

    def __init__(self) -> None:
        self.permissions_by_user_id: dict[int, Privileges] = {}
        self.calls: list[int] = []

    async def compute_permissions(self, user_id: int) -> Privileges:
        self.calls.append(user_id)
        return self.permissions_by_user_id.get(user_id, Privileges.NONE)


class FriendEligibleUserIdsQueryStub:
    """Typed friend eligibility query test double for Friends leaderboard scopes."""

    def __init__(self) -> None:
        self.result_by_viewer_user_id: dict[int, tuple[int, ...]] = {}
        self.calls: list[int] = []

    async def execute(self, *, viewer_user_id: int) -> tuple[int, ...]:
        self.calls.append(viewer_user_id)
        return self.result_by_viewer_user_id.get(viewer_user_id, (viewer_user_id,))


@pytest.fixture
def getscores_repo() -> BeatmapScoreListingQueryRepositoryStub:
    return BeatmapScoreListingQueryRepositoryStub()


@pytest.fixture
def leaderboard_repo() -> BeatmapLeaderboardQueryRepositoryStub:
    return BeatmapLeaderboardQueryRepositoryStub()


@pytest.fixture
def user_repo() -> ViewerUserQueryRepositoryStub:
    return ViewerUserQueryRepositoryStub()


@pytest.fixture
def permission_service() -> ViewerPermissionServiceStub:
    return ViewerPermissionServiceStub()


@pytest.fixture
def friend_query() -> FriendEligibleUserIdsQueryStub:
    return FriendEligibleUserIdsQueryStub()


@pytest.fixture
def sample_beatmap() -> Beatmap:
    return Beatmap(
        id=75,
        beatmapset_id=5,
        checksum_md5=_CHECKSUM,
        mode="osu",
        version="Insane",
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.AVAILABLE,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=None,
    )


@pytest.fixture
def sample_beatmapset() -> BeatmapSet:
    return BeatmapSet(
        id=5,
        artist="Artist",
        title="Title",
        creator="Creator",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(),
        last_fetched_at=_NOW,
        next_refresh_at=None,
    )


class TestBeatmapLeaderboardQuery:
    async def test_unknown_checksum_with_pending_fetch_state_returns_pending_fetch(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
    ) -> None:
        target = BeatmapFetchTarget.metadata_by_checksum(_CHECKSUM)
        getscores_repo.fetch_records[target] = BeatmapFetchRecord(
            target=target,
            status=BeatmapFetchState.PENDING_FETCH,
            attempt_count=1,
            last_error=None,
            pending_since=_NOW,
            last_attempted_at=_NOW,
        )

        result = await _query(getscores_repo, leaderboard_repo).resolve(
            _request(filename=_FILENAME),
            user_id=9,
        )

        assert result.kind is BeatmapLeaderboardOutcomeKind.UNAVAILABLE
        assert result.reason is BeatmapLeaderboardResolveReason.PENDING_FETCH

    async def test_unknown_checksum_with_failed_fetch_state_returns_failed_metadata(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
    ) -> None:
        target = BeatmapFetchTarget.metadata_by_checksum(_CHECKSUM)
        getscores_repo.fetch_records[target] = BeatmapFetchRecord(
            target=target,
            status=BeatmapFetchState.FAILED,
            attempt_count=1,
            last_error="not found",
            pending_since=None,
            last_attempted_at=_NOW,
        )

        result = await _query(getscores_repo, leaderboard_repo).resolve(
            _request(filename=_FILENAME),
            user_id=9,
        )

        assert result.kind is BeatmapLeaderboardOutcomeKind.UNAVAILABLE
        assert result.reason is BeatmapLeaderboardResolveReason.FAILED_METADATA

    async def test_available_ranked_local_request_reads_global_rows_and_personal_best(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        user_repo: ViewerUserQueryRepositoryStub,
        permission_service: ViewerPermissionServiceStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset
        row = _leaderboard_row(score_id=10, user_id=20, rank=1)
        personal_best = _leaderboard_row(score_id=11, user_id=9, rank=4)
        leaderboard_repo.rows = (row,)
        leaderboard_repo.personal_best = personal_best
        _add_viewer(
            user_repo,
            permission_service,
            user_id=9,
            permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
        )

        result = await _query(
            getscores_repo,
            leaderboard_repo,
            user_repo=user_repo,
            permission_service=permission_service,
        ).resolve(
            _request(leaderboard_type=1),
            user_id=9,
        )

        assert result.kind is BeatmapLeaderboardOutcomeKind.HEADER
        assert result.header is not None
        assert result.rows == (row,)
        assert result.personal_best == personal_best
        assert leaderboard_repo.top_row_calls == [
            (
                LeaderboardReadScope(
                    beatmap_id=sample_beatmap.id,
                    beatmap_checksum=sample_beatmap.checksum_md5,
                    ruleset=Ruleset.OSU,
                    playstyle=Playstyle.VANILLA,
                    category=LeaderboardCategory.GLOBAL,
                    mod_filter_key=None,
                ),
                50,
            )
        ]
        assert leaderboard_repo.personal_best_calls == [(leaderboard_repo.top_row_calls[0][0], 9)]

    async def test_personal_best_outside_top_50_is_returned_separately(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        user_repo: ViewerUserQueryRepositoryStub,
        permission_service: ViewerPermissionServiceStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset
        rows = tuple(
            _leaderboard_row(score_id=score_id, user_id=score_id, rank=rank)
            for rank, score_id in enumerate(range(100, 150), start=1)
        )
        personal_best = _leaderboard_row(score_id=200, user_id=9, rank=51)
        leaderboard_repo.rows = rows
        leaderboard_repo.personal_best = personal_best
        _add_viewer(
            user_repo,
            permission_service,
            user_id=9,
            permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
        )

        result = await _query(
            getscores_repo,
            leaderboard_repo,
            user_repo=user_repo,
            permission_service=permission_service,
        ).resolve(
            _request(leaderboard_type=1),
            user_id=9,
        )

        assert result.header is not None
        assert len(result.rows) == 50
        assert all(row.user_id != 9 for row in result.rows)
        assert result.personal_best == personal_best
        personal_best_row = result.personal_best
        assert personal_best_row is not None
        assert personal_best_row.rank == 51

    async def test_personal_best_duplicate_in_rows_is_returned_twice(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        user_repo: ViewerUserQueryRepositoryStub,
        permission_service: ViewerPermissionServiceStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset
        personal_best = _leaderboard_row(score_id=10, user_id=9, rank=1)
        leaderboard_repo.rows = (personal_best,)
        leaderboard_repo.personal_best = personal_best
        _add_viewer(
            user_repo,
            permission_service,
            user_id=9,
            permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
        )

        result = await _query(
            getscores_repo,
            leaderboard_repo,
            user_repo=user_repo,
            permission_service=permission_service,
        ).resolve(
            _request(leaderboard_type=1),
            user_id=9,
        )

        assert result.header is not None
        expected_row = personal_best
        assert result.rows == (expected_row,)
        assert result.personal_best == expected_row

    async def test_selected_mods_personal_best_uses_selected_mod_scope(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        user_repo: ViewerUserQueryRepositoryStub,
        permission_service: ViewerPermissionServiceStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset
        personal_best = _leaderboard_row(score_id=10, user_id=9, rank=1)
        leaderboard_repo.personal_best = personal_best
        _add_viewer(
            user_repo,
            permission_service,
            user_id=9,
            permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
        )

        result = await _query(
            getscores_repo,
            leaderboard_repo,
            user_repo=user_repo,
            permission_service=permission_service,
        ).resolve(
            _request(leaderboard_type=2, mods=int(Mod.DOUBLE_TIME)),
            user_id=9,
        )

        assert result.header is not None
        assert result.personal_best == personal_best
        assert leaderboard_repo.personal_best_calls == [
            (
                LeaderboardReadScope(
                    beatmap_id=sample_beatmap.id,
                    beatmap_checksum=sample_beatmap.checksum_md5,
                    ruleset=Ruleset.OSU,
                    playstyle=Playstyle.VANILLA,
                    category=LeaderboardCategory.SELECTED_MODS,
                    mod_filter_key=int(Mod.DOUBLE_TIME),
                ),
                9,
            )
        ]

    async def test_country_scope_uses_viewer_country_and_all_mods(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        user_repo: ViewerUserQueryRepositoryStub,
        permission_service: ViewerPermissionServiceStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset
        personal_best = _leaderboard_row(score_id=10, user_id=9, rank=1)
        leaderboard_repo.personal_best = personal_best
        _add_viewer(
            user_repo,
            permission_service,
            user_id=9,
            country="JP",
            permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
        )

        result = await _query(
            getscores_repo,
            leaderboard_repo,
            user_repo=user_repo,
            permission_service=permission_service,
        ).resolve(
            _request(leaderboard_type=4, mods=int(Mod.DOUBLE_TIME)),
            user_id=9,
        )

        expected_scope = LeaderboardReadScope(
            beatmap_id=sample_beatmap.id,
            beatmap_checksum=sample_beatmap.checksum_md5,
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
            category=LeaderboardCategory.COUNTRY,
            mod_filter_key=None,
            country="JP",
        )
        assert result.header is not None
        assert result.personal_best == personal_best
        assert leaderboard_repo.top_row_calls == [(expected_scope, 50)]
        assert leaderboard_repo.personal_best_calls == [(expected_scope, 9)]

    async def test_country_scope_with_unknown_or_missing_country_returns_header_only(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        user_repo: ViewerUserQueryRepositoryStub,
        permission_service: ViewerPermissionServiceStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset
        _add_viewer(
            user_repo,
            permission_service,
            user_id=9,
            country="XX",
            permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
        )

        result = await _query(
            getscores_repo,
            leaderboard_repo,
            user_repo=user_repo,
            permission_service=permission_service,
        ).resolve(
            _request(leaderboard_type=4),
            user_id=9,
        )

        assert result.header is not None
        assert result.rows == ()
        assert result.personal_best is None
        assert leaderboard_repo.top_row_calls == []
        assert leaderboard_repo.personal_best_calls == []

        user_repo.users_by_id.clear()

        result = await _query(
            getscores_repo,
            leaderboard_repo,
            user_repo=user_repo,
            permission_service=permission_service,
        ).resolve(
            _request(leaderboard_type=4),
            user_id=9,
        )

        assert result.header is not None
        assert result.rows == ()
        assert result.personal_best is None
        assert leaderboard_repo.top_row_calls == []
        assert leaderboard_repo.personal_best_calls == []

    async def test_friends_scope_uses_friend_eligible_ids_and_all_mods(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        user_repo: ViewerUserQueryRepositoryStub,
        permission_service: ViewerPermissionServiceStub,
        friend_query: FriendEligibleUserIdsQueryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset
        friend_query.result_by_viewer_user_id[9] = (9, 20)
        personal_best = _leaderboard_row(score_id=10, user_id=9, rank=1)
        leaderboard_repo.personal_best = personal_best
        _add_viewer(
            user_repo,
            permission_service,
            user_id=9,
            permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
        )

        result = await _query(
            getscores_repo,
            leaderboard_repo,
            user_repo=user_repo,
            permission_service=permission_service,
            friend_query=friend_query,
        ).resolve(
            _request(leaderboard_type=3, mods=int(Mod.DOUBLE_TIME)),
            user_id=9,
        )

        expected_scope = LeaderboardReadScope(
            beatmap_id=sample_beatmap.id,
            beatmap_checksum=sample_beatmap.checksum_md5,
            ruleset=Ruleset.OSU,
            playstyle=Playstyle.VANILLA,
            category=LeaderboardCategory.FRIENDS,
            mod_filter_key=None,
            eligible_user_ids=(9, 20),
        )
        assert result.header is not None
        assert result.personal_best == personal_best
        assert friend_query.calls == [9]
        assert leaderboard_repo.top_row_calls == [(expected_scope, 50)]
        assert leaderboard_repo.personal_best_calls == [(expected_scope, 9)]

    async def test_non_visible_viewer_suppresses_pb_but_returns_public_rows(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        user_repo: ViewerUserQueryRepositoryStub,
        permission_service: ViewerPermissionServiceStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset
        row = _leaderboard_row(score_id=10, user_id=20, rank=1)
        leaderboard_repo.rows = (row,)
        leaderboard_repo.personal_best = _leaderboard_row(score_id=11, user_id=9, rank=2)
        _add_viewer(
            user_repo,
            permission_service,
            user_id=9,
            permissions=Privileges.NORMAL,
        )

        result = await _query(
            getscores_repo,
            leaderboard_repo,
            user_repo=user_repo,
            permission_service=permission_service,
        ).resolve(
            _request(leaderboard_type=1),
            user_id=9,
        )

        assert result.header is not None
        assert result.rows == (row,)
        assert result.personal_best is None
        assert leaderboard_repo.top_row_calls == [
            (
                LeaderboardReadScope(
                    beatmap_id=sample_beatmap.id,
                    beatmap_checksum=sample_beatmap.checksum_md5,
                    ruleset=Ruleset.OSU,
                    playstyle=Playstyle.VANILLA,
                    category=LeaderboardCategory.GLOBAL,
                    mod_filter_key=None,
                ),
                50,
            )
        ]
        assert leaderboard_repo.personal_best_calls == []

    async def test_supported_visibility_statuses_are_available_for_rows(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        for status in (
            BeatmapRankStatus.RANKED,
            BeatmapRankStatus.APPROVED,
            BeatmapRankStatus.LOVED,
            BeatmapRankStatus.QUALIFIED,
        ):
            getscores_repo.beatmaps_by_checksum.clear()
            getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset
            getscores_repo.beatmaps_by_checksum[_CHECKSUM] = replace(
                sample_beatmap,
                official_status=status,
            )
            leaderboard_repo.top_row_calls.clear()

            result = await _query(getscores_repo, leaderboard_repo).resolve(
                _request(),
                user_id=9,
            )

            assert result.kind is BeatmapLeaderboardOutcomeKind.HEADER
            assert len(leaderboard_repo.top_row_calls) == 1

    async def test_unsupported_category_returns_header_only_without_global_fallback(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        result = await _query(getscores_repo, leaderboard_repo).resolve(
            _request(leaderboard_type=99),
            user_id=9,
        )

        assert result.kind is BeatmapLeaderboardOutcomeKind.HEADER
        assert result.header is not None
        assert result.rows == ()
        assert result.personal_best is None
        assert leaderboard_repo.top_row_calls == []
        assert leaderboard_repo.personal_best_calls == []

    async def test_displayable_but_not_leaderboard_visible_status_returns_header_only(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = replace(
            sample_beatmap,
            official_status=BeatmapRankStatus.PENDING,
        )
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        result = await _query(getscores_repo, leaderboard_repo).resolve(
            _request(),
            user_id=9,
        )

        assert result.kind is BeatmapLeaderboardOutcomeKind.HEADER
        assert result.header is not None
        assert result.rows == ()
        assert result.personal_best is None
        assert leaderboard_repo.top_row_calls == []

    async def test_missing_category_context_returns_header_only(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        result = await _query(getscores_repo, leaderboard_repo).resolve(
            _request(leaderboard_type=None),
            user_id=9,
        )

        assert result.kind is BeatmapLeaderboardOutcomeKind.HEADER
        assert result.header is not None
        assert result.rows == ()
        assert result.personal_best is None
        assert leaderboard_repo.top_row_calls == []

    async def test_non_vanilla_mod_request_returns_header_only(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        result = await _query(getscores_repo, leaderboard_repo).resolve(
            _request(mods=int(Mod.RELAX)),
            user_id=9,
        )

        assert result.kind is BeatmapLeaderboardOutcomeKind.HEADER
        assert result.header is not None
        assert result.rows == ()
        assert result.personal_best is None
        assert leaderboard_repo.top_row_calls == []

    async def test_song_select_request_returns_header_only(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        result = await _query(getscores_repo, leaderboard_repo).resolve(
            _request(song_select=True),
            user_id=9,
        )

        assert result.kind is BeatmapLeaderboardOutcomeKind.HEADER
        assert result.header is not None
        assert result.rows == ()
        assert result.personal_best is None
        assert leaderboard_repo.top_row_calls == []

    async def test_outdated_checksum_returns_update_available_without_rows(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_filename[(sample_beatmap.beatmapset_id, _FILENAME)] = (
            sample_beatmap
        )
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        result = await _query(getscores_repo, leaderboard_repo).resolve(
            _request(checksum_md5=_OLD_CHECKSUM, filename=_FILENAME),
            user_id=9,
        )

        assert result.kind is BeatmapLeaderboardOutcomeKind.UPDATE_AVAILABLE
        assert result.header is not None
        assert result.rows == ()
        assert result.personal_best is None
        assert result.reason is BeatmapLeaderboardResolveReason.UPDATE_AVAILABLE
        assert leaderboard_repo.top_row_calls == []

    async def test_unauthenticated_viewer_dependent_category_returns_header_only(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
        sample_beatmap: Beatmap,
        sample_beatmapset: BeatmapSet,
    ) -> None:
        getscores_repo.beatmaps_by_checksum[sample_beatmap.checksum_md5] = sample_beatmap
        getscores_repo.beatmapsets_by_id[sample_beatmapset.id] = sample_beatmapset

        result = await _query(getscores_repo, leaderboard_repo).resolve(
            _request(leaderboard_type=3),
            user_id=None,
        )

        assert result.kind is BeatmapLeaderboardOutcomeKind.HEADER
        assert result.header is not None
        assert result.rows == ()
        assert result.personal_best is None
        assert leaderboard_repo.top_row_calls == []


@dataclass(slots=True)
class _BeatmapLeaderboardQueryHarness:
    query: BeatmapLeaderboardQuery

    async def resolve(
        self,
        request: BeatmapLeaderboardRequest,
        *,
        user_id: int | None = None,
    ) -> BeatmapLeaderboardResult:
        return await self.query.execute(replace(request, viewer_user_id=user_id))


def _query(
    getscores_repo: BeatmapScoreListingQueryRepositoryStub,
    leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
    *,
    user_repo: ViewerUserQueryRepositoryStub | None = None,
    permission_service: ViewerPermissionServiceStub | None = None,
    friend_query: FriendEligibleUserIdsQueryStub | None = None,
) -> _BeatmapLeaderboardQueryHarness:
    return _BeatmapLeaderboardQueryHarness(
        query=BeatmapLeaderboardQuery(
            getscores_repo,
            leaderboard_repo,
            user_repository=user_repo,
            permission_service=permission_service,
            friend_eligible_user_ids_query=friend_query,
        )
    )


def _request(
    *,
    checksum_md5: str = _CHECKSUM,
    filename: str | None = None,
    mode: int | None = Ruleset.OSU.value,
    mods: int | None = 0,
    leaderboard_type: int | None = 1,
    song_select: bool | None = False,
) -> BeatmapLeaderboardRequest:
    ruleset = _ruleset_from_mode(mode)
    category = _leaderboard_category_from_type(leaderboard_type)
    header_only = category is None or song_select is True
    selected_mod_filter = None

    if mods is None:
        header_only = True
    else:
        mod_combination = ModCombination.from_bitmask(mods)
        if mod_combination.has(Mod.RELAX) or mod_combination.has(Mod.AUTOPILOT):
            header_only = True
        if category is LeaderboardCategory.SELECTED_MODS:
            selected_mod_filter = filter_from_mod_combination(mod_combination)
            if not selected_mod_filter.is_supported:
                header_only = True

    return BeatmapLeaderboardRequest(
        beatmap_checksum=checksum_md5,
        filename=filename,
        beatmapset_id_hint=5,
        viewer_user_id=None,
        ruleset=ruleset,
        playstyle=Playstyle.VANILLA,
        category=category,
        selected_mod_filter=selected_mod_filter,
        header_only=header_only,
    )


def _ruleset_from_mode(mode: int | None) -> Ruleset | None:
    if mode is None:
        return None
    try:
        return Ruleset(mode)
    except ValueError:
        return None


def _leaderboard_category_from_type(
    leaderboard_type: int | None,
) -> LeaderboardCategory | None:
    if leaderboard_type is None:
        return None
    return {
        1: LeaderboardCategory.GLOBAL,
        2: LeaderboardCategory.SELECTED_MODS,
        3: LeaderboardCategory.FRIENDS,
        4: LeaderboardCategory.COUNTRY,
    }.get(leaderboard_type)


def _leaderboard_row(
    *,
    score_id: int,
    user_id: int,
    rank: int,
) -> BeatmapLeaderboardRow:
    return BeatmapLeaderboardRow(
        score_id=score_id,
        user_id=user_id,
        username=f"user-{user_id}",
        beatmap_id=75,
        ruleset=Ruleset.OSU,
        playstyle=Playstyle.VANILLA,
        score=1_000_000 - score_id,
        max_combo=500,
        hit_counts=ScoreHitCounts(n50=1, n100=2, n300=300, miss=3, katu=4, geki=5),
        perfect=True,
        displayed_mods=ModCombination.none(),
        rank=rank,
        submitted_at=_NOW,
        has_replay=True,
        pp=Decimal("123.45"),
    )


def _add_viewer(
    user_repo: ViewerUserQueryRepositoryStub,
    permission_service: ViewerPermissionServiceStub,
    *,
    user_id: int,
    country: str = "JP",
    permissions: Privileges,
) -> None:
    user_repo.users_by_id[user_id] = User(
        id=user_id,
        username=f"user-{user_id}",
        safe_username=f"user_{user_id}",
        email=f"user-{user_id}@example.com",
        password_hash="hashed",
        country=country,
        created_at=_NOW,
        updated_at=_NOW,
    )
    permission_service.permissions_by_user_id[user_id] = permissions
