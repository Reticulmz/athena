"""Beatmap leaderboard queryの契約を検証するunit test群."""

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
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.users import User
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
    """Beatmap score listing queryを再現するtyped stub.

    Attributes:
        beatmaps_by_checksum (dict[str, Beatmap]): checksumごとのbeatmap read結果.
        beatmaps_by_filename (dict[tuple[int, str], Beatmap]): filename lookup結果.
        beatmapsets_by_id (dict[int, BeatmapSet]): IDごとのbeatmapset read結果.
        fetch_records (dict[BeatmapFetchTarget, BeatmapFetchRecord]): fetch state.
    """

    def __init__(self) -> None:
        """空のscore listing read状態を初期化する."""
        self.beatmaps_by_checksum: dict[str, Beatmap] = {}
        self.beatmaps_by_filename: dict[tuple[int, str], Beatmap] = {}
        self.beatmapsets_by_id: dict[int, BeatmapSet] = {}
        self.fetch_records: dict[BeatmapFetchTarget, BeatmapFetchRecord] = {}

    async def find_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """checksumに対応するbeatmapを返す.

        Args:
            checksum_md5 (str): 検索対象のMD5 checksum.

        Returns:
            Beatmap | None: 登録済みのbeatmap. 見つからない場合はNone.
        """
        return self.beatmaps_by_checksum.get(checksum_md5)

    async def find_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """beatmapset内の元filenameに対応するbeatmapを返す.

        Args:
            beatmapset_id (int): 検索対象のbeatmapset ID.
            original_filename (str): beatmapset内で照合する元filename.

        Returns:
            Beatmap | None: 登録済みのbeatmap. 見つからない場合はNone.
        """
        return self.beatmaps_by_filename.get((beatmapset_id, original_filename))

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """IDに対応するbeatmapsetを返す.

        Args:
            beatmapset_id (int): 検索対象のbeatmapset ID.

        Returns:
            BeatmapSet | None: 登録済みのbeatmapset. 見つからない場合はNone.
        """
        return self.beatmapsets_by_id.get(beatmapset_id)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Metadata fetch targetの現在記録を返す.

        Args:
            target (BeatmapFetchTarget): 照合対象のmetadata取得先.

        Returns:
            BeatmapFetchRecord | None: 登録済みの取得記録. 存在しない場合はNone.
        """
        return self.fetch_records.get(target)


class BeatmapLeaderboardQueryRepositoryStub:
    """Leaderboard queryのread結果と呼出記録を提供するtyped stub.

    Attributes:
        rows (tuple[BeatmapLeaderboardRow, ...]): top row readで返す順位行.
        personal_best (BeatmapLeaderboardRow | None): personal best readで返す順位行.
        top_row_calls (list[tuple[LeaderboardReadScope, int]]): top row read記録.
        personal_best_calls (list[tuple[LeaderboardReadScope, int]]): personal best read記録.
    """

    def __init__(self) -> None:
        """空のleaderboard read状態と呼出記録を初期化する."""
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
        """指定scopeのtop rowを返し、read条件を記録する.

        Args:
            scope (LeaderboardReadScope): leaderboardを絞り込む条件.
            limit (int): 返却を要求する最大行数.

        Returns:
            tuple[BeatmapLeaderboardRow, ...]: 事前設定した順位行.
        """
        self.top_row_calls.append((scope, limit))
        return self.rows

    async def get_personal_best(
        self,
        scope: LeaderboardReadScope,
        *,
        viewer_user_id: int,
    ) -> BeatmapLeaderboardRow | None:
        """指定viewerのpersonal bestを返し、read条件を記録する.

        Args:
            scope (LeaderboardReadScope): personal bestを絞り込む条件.
            viewer_user_id (int): personal bestを取得するviewerのuser ID.

        Returns:
            BeatmapLeaderboardRow | None: 事前設定したpersonal best. 未設定の場合はNone.
        """
        self.personal_best_calls.append((scope, viewer_user_id))
        return self.personal_best


class ViewerUserQueryRepositoryStub:
    """Viewer context解決用のuser readを再現するtyped stub.

    Attributes:
        users_by_id (dict[int, User]): user IDごとのviewer user.
        calls (list[int]): ID検索の呼出記録.
        safe_username_calls (list[str]): safe username検索の呼出記録.
        email_calls (list[str]): email検索の呼出記録.
        username_disallowed_calls (list[str]): username禁止判定の呼出記録.
    """

    def __init__(self) -> None:
        """空のviewer user read状態と呼出記録を初期化する."""
        self.users_by_id: dict[int, User] = {}
        self.calls: list[int] = []
        self.safe_username_calls: list[str] = []
        self.email_calls: list[str] = []
        self.username_disallowed_calls: list[str] = []

    async def get_by_id(self, user_id: int) -> User | None:
        """IDに対応するviewer userを返す.

        Args:
            user_id (int): 取得対象のuser ID.

        Returns:
            User | None: 登録済みのviewer user. 見つからない場合はNone.
        """
        self.calls.append(user_id)
        return self.users_by_id.get(user_id)

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Safe username検索の呼出を記録して未検出を返す.

        Args:
            safe_username (str): 検索対象のsafe username.

        Returns:
            User | None: このstubでは常にNone.
        """
        self.safe_username_calls.append(safe_username)
        return None

    async def get_by_email(self, email: str) -> User | None:
        """email検索の呼出を記録して未検出を返す.

        Args:
            email (str): 検索対象のemail address.

        Returns:
            User | None: このstubでは常にNone.
        """
        self.email_calls.append(email)
        return None

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """username禁止判定の呼出を記録して許可を返す.

        Args:
            safe_username (str): 判定対象のsafe username.

        Returns:
            bool: このstubでは常にFalse.
        """
        self.username_disallowed_calls.append(safe_username)
        return False


class ViewerPermissionServiceStub:
    """Viewer visibility判定用permission serviceを再現するtyped stub.

    Attributes:
        permissions_by_user_id (dict[int, Privileges]): user IDごとのpermission result.
        calls (list[int]): permission計算の呼出記録.
    """

    def __init__(self) -> None:
        """空のpermission resultと呼出記録を初期化する."""
        self.permissions_by_user_id: dict[int, Privileges] = {}
        self.calls: list[int] = []

    async def compute_permissions(self, user_id: int) -> Privileges:
        """userのpermissionを返し、計算対象を記録する.

        Args:
            user_id (int): permissionを求めるviewerのuser ID.

        Returns:
            Privileges: 事前設定したpermission. 未設定の場合はPrivileges.NONE.
        """
        self.calls.append(user_id)
        return self.permissions_by_user_id.get(user_id, Privileges.NONE)


class FriendEligibleUserIdsQueryStub:
    """Friends leaderboard用eligible user ID queryを再現するtyped stub.

    Attributes:
        result_by_viewer_user_id (dict[int, tuple[int, ...]]): viewer IDごとのeligible user ID列.
        calls (list[int]): query実行のviewer ID記録.
    """

    def __init__(self) -> None:
        """空のeligible user resultと呼出記録を初期化する."""
        self.result_by_viewer_user_id: dict[int, tuple[int, ...]] = {}
        self.calls: list[int] = []

    async def execute(self, *, viewer_user_id: int) -> tuple[int, ...]:
        """viewerのeligible friend ID列を返す.

        Args:
            viewer_user_id (int): Friends scopeを要求したviewerのuser ID.

        Returns:
            tuple[int, ...]: 事前設定したeligible user ID列. 未設定の場合はviewer自身だけの列.
        """
        self.calls.append(viewer_user_id)
        return self.result_by_viewer_user_id.get(viewer_user_id, (viewer_user_id,))


@pytest.fixture
def getscores_repo() -> BeatmapScoreListingQueryRepositoryStub:
    """空のscore listing repository stubを提供する.

    Returns:
        BeatmapScoreListingQueryRepositoryStub: beatmapとfetch stateを個別に設定できるstub.
    """
    return BeatmapScoreListingQueryRepositoryStub()


@pytest.fixture
def leaderboard_repo() -> BeatmapLeaderboardQueryRepositoryStub:
    """空のleaderboard repository stubを提供する.

    Returns:
        BeatmapLeaderboardQueryRepositoryStub: rowとpersonal bestを設定できるstub.
    """
    return BeatmapLeaderboardQueryRepositoryStub()


@pytest.fixture
def user_repo() -> ViewerUserQueryRepositoryStub:
    """空のviewer user repository stubを提供する.

    Returns:
        ViewerUserQueryRepositoryStub: viewer userをIDごとに設定できるstub.
    """
    return ViewerUserQueryRepositoryStub()


@pytest.fixture
def permission_service() -> ViewerPermissionServiceStub:
    """空のviewer permission service stubを提供する.

    Returns:
        ViewerPermissionServiceStub: viewer visibility用permissionを設定できるstub.
    """
    return ViewerPermissionServiceStub()


@pytest.fixture
def friend_query() -> FriendEligibleUserIdsQueryStub:
    """空のfriend eligibility query stubを提供する.

    Returns:
        FriendEligibleUserIdsQueryStub: viewerごとのeligible ID列を設定できるstub.
    """
    return FriendEligibleUserIdsQueryStub()


@pytest.fixture
def sample_beatmap() -> Beatmap:
    """Rankedかつfile availableの標準beatmap fixtureを提供する.

    Returns:
        Beatmap: leaderboard readの前提を満たすosu! modeのbeatmap.
    """
    return Beatmap(
        id=75,
        beatmapset_id=5,
        checksum_md5=_CHECKSUM,
        mode=BeatmapMode.OSU,
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
    """標準beatmap fixtureと対応するranked beatmapsetを提供する.

    Returns:
        BeatmapSet: ID 5のranked beatmapset.
    """
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
    """Beatmap leaderboard queryのscope選択とheader-only条件を検証する."""

    async def test_unknown_checksum_with_pending_fetch_state_returns_pending_fetch(
        self,
        getscores_repo: BeatmapScoreListingQueryRepositoryStub,
        leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
    ) -> None:
        """未取得checksumのPENDING_FETCHをunavailableへ写像する契約を検証する.

        PENDING_FETCHのmetadata記録を用意してresolveし、observable outcomeがUNAVAILABLEかつ
        PENDING_FETCH reasonになることを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): fetch stateを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): readを観測するstub.

        Returns:
            None: unavailable resultを検証して値を返さずに完了する.
        """
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
        """未取得checksumのFAILED fetch stateをmetadata failureへ写像する契約を検証する.

        FAILEDのmetadata記録を用意してresolveし、observable outcomeがUNAVAILABLEかつ
        FAILED_METADATA reasonになることを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): fetch stateを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): readを観測するstub.

        Returns:
            None: failed metadata resultを検証して値を返さずに完了する.
        """
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
        """Ranked local requestがglobal rowsとpersonal bestをreadする契約を検証する.

        Visibleなviewerとranked beatmapを用意してGLOBAL requestをresolveする.
        Observable outcomeとして50件limitのglobal scopeとpersonal bestが返ることを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): row readを記録するstub.
            user_repo (ViewerUserQueryRepositoryStub): viewerを設定するstub.
            permission_service (ViewerPermissionServiceStub): viewer permissionを設定するstub.
            sample_beatmap (Beatmap): rankedかつavailableなbeatmap fixture.
            sample_beatmapset (BeatmapSet): beatmapに対応するbeatmapset fixture.

        Returns:
            None: global rowとpersonal bestのobservable outcomeを検証して値を返さずに完了する.
        """
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
        """Top 50外のpersonal bestを別欄に残す契約を検証する.

        50行のglobal rowsと51位のviewer scoreを用意してresolveし、observable outcomeとしてrowsへ
        viewer scoreを混在させずpersonal_bestに返すことを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): row結果を設定するstub.
            user_repo (ViewerUserQueryRepositoryStub): visible viewerを設定するstub.
            permission_service (ViewerPermissionServiceStub): visible permissionを設定するstub.
            sample_beatmap (Beatmap): leaderboard対象のbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: top 50と別のpersonal bestを検証して値を返さずに完了する.
        """
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
        """Top rows内のpersonal bestもpersonal_best欄へ重複して返す契約を検証する.

        viewerの同一scoreをtop rowとpersonal bestに設定してresolveし、observable outcomeとして
        rowsとpersonal_bestの両方がそのscoreを保持することを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): 同一scoreを設定するstub.
            user_repo (ViewerUserQueryRepositoryStub): visible viewerを設定するstub.
            permission_service (ViewerPermissionServiceStub): visible permissionを設定するstub.
            sample_beatmap (Beatmap): leaderboard対象のbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: duplicated personal bestのobservable outcomeを検証して値を返さずに完了する.
        """
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
        """Selected mods requestがselected mod scopeでpersonal bestをreadする契約を検証する.

        DOUBLE_TIME requestとvisible viewerを用意してresolveし、observable outcomeとして
        SELECTED_MODS scopeにDOUBLE_TIMEを含むpersonal best readが行われることを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): personal best read用stub.
            user_repo (ViewerUserQueryRepositoryStub): visible viewerを設定するstub.
            permission_service (ViewerPermissionServiceStub): visible permissionを設定するstub.
            sample_beatmap (Beatmap): leaderboard対象のbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: selected mod scopeのpersonal best readを検証して値を返さずに完了する.
        """
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
                    selected_mods=ModCombination(Mod.DOUBLE_TIME),
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
        """Country scopeがviewer countryを使いmodsを限定しない契約を検証する.

        JPのvisible viewerとDOUBLE_TIME requestを用意してresolveし、observable outcomeとして
        COUNTRY scopeがJPを持ちselected modsなしでrowsとpersonal bestをreadすることを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): country readを記録するstub.
            user_repo (ViewerUserQueryRepositoryStub): JP viewerを設定するstub.
            permission_service (ViewerPermissionServiceStub): visible permissionを設定するstub.
            sample_beatmap (Beatmap): leaderboard対象のbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: country scopeのrowとpersonal best readを検証して値を返さずに完了する.
        """
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
        """未知または未解決のcountryではCountry scopeをheader-onlyにする契約を検証する.

        XX countryのviewerとその後の欠落viewerを用意してresolveし、observable outcomeとして
        rowsとpersonal bestを返さずleaderboard readも行わないことを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): read未実行を観測するstub.
            user_repo (ViewerUserQueryRepositoryStub): country不明と欠落のviewer状態を設定するstub.
            permission_service (ViewerPermissionServiceStub): visible permissionを設定するstub.
            sample_beatmap (Beatmap): leaderboard対象のbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: country不明時のheader-only outcomeを検証して値を返さずに完了する.
        """
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
        """Friends scopeがeligible user ID列を使いmodsを限定しない契約を検証する.

        viewerを含むeligible ID列とDOUBLE_TIME requestを用意してresolveする.
        Observable outcomeとしてFRIENDS scopeがID列を持つことを確認する.
        さらにrowsとpersonal bestをreadすることを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): friends readを記録するstub.
            user_repo (ViewerUserQueryRepositoryStub): visible viewerを設定するstub.
            permission_service (ViewerPermissionServiceStub): visible permissionを設定するstub.
            friend_query (FriendEligibleUserIdsQueryStub): eligible ID列を返すstub.
            sample_beatmap (Beatmap): leaderboard対象のbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: eligible ID readを検証して値を返さずに完了する.
        """
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
        """Visibilityを持たないviewerではpublic rowsだけを返す契約を検証する.

        UNRESTRICTEDを持たないviewerとpublic rowを用意してresolveし、observable outcomeとして
        row readは維持しpersonal best readと返却を抑止することを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): public rowを設定するstub.
            user_repo (ViewerUserQueryRepositoryStub): non-visible viewerを設定するstub.
            permission_service (ViewerPermissionServiceStub): permissionを設定するstub.
            sample_beatmap (Beatmap): leaderboard対象のbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: public rows維持とpersonal best抑止を検証して値を返さずに完了する.
        """
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
        """Leaderboard表示対象のrank statusでrow readを許可する契約を検証する.

        RANKED、APPROVED、LOVED、QUALIFIEDのbeatmapを順に用意してresolveする.
        Observable outcomeとして各statusがHEADERと1回のtop row readを返すことを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): status別beatmapを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): top row readを観測するstub.
            sample_beatmap (Beatmap): statusを差し替える基底beatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: 各表示対象statusのrow readを検証して値を返さずに完了する.
        """
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
        """未知のleaderboard categoryをGLOBALへfallbackしない契約を検証する.

        未対応categoryのrequestと取得可能なbeatmapを用意してresolveし、observable outcomeとして
        HEADERだけを返しrowとpersonal bestのreadを行わないことを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): read未実行を観測するstub.
            sample_beatmap (Beatmap): leaderboard対象のbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: unsupported categoryのheader-only outcomeを検証して値を返さずに完了する.
        """
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
        """表示可能でもleaderboard非表示のstatusをheader-onlyにする契約を検証する.

        PENDING beatmapと対応beatmapsetを用意してresolveし、observable outcomeとしてHEADERだけを
        返しtop row readを行わないことを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): PENDING beatmapを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): read未実行を観測するstub.
            sample_beatmap (Beatmap): statusを差し替える基底beatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: leaderboard非表示statusのheader-only outcomeを検証して値を返さずに完了する.
        """
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
        """Category contextがないrequestをheader-onlyにする契約を検証する.

        categoryなしのrequestと取得可能なbeatmapを用意してresolveし、observable outcomeとして
        rowsとpersonal bestなしのHEADERを返しtop row readを行わないことを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): read未実行を観測するstub.
            sample_beatmap (Beatmap): leaderboard対象のbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: categoryなしのheader-only outcomeを検証して値を返さずに完了する.
        """
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
        """Non-vanilla mod requestをheader-onlyにする契約を検証する.

        RELAXを含むrequestと取得可能なbeatmapを用意してresolveし、observable outcomeとして
        rowsとpersonal bestなしのHEADERを返しtop row readを行わないことを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): read未実行を観測するstub.
            sample_beatmap (Beatmap): leaderboard対象のbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: non-vanilla modのheader-only outcomeを検証して値を返さずに完了する.
        """
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
        """Song select requestでleaderboard readを抑止する契約を検証する.

        song_selectがtrueのrequestと取得可能なbeatmapを用意してresolveし、observable outcomeとして
        rowsとpersonal bestなしのHEADERを返しtop row readを行わないことを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): read未実行を観測するstub.
            sample_beatmap (Beatmap): leaderboard対象のbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: song selectのheader-only outcomeを検証して値を返さずに完了する.
        """
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
        """Checksum missとfilename matchをUPDATE_AVAILABLEへ写像する契約を検証する.

        古いchecksumと一致するfilenameのbeatmapを用意してresolveし、observable outcomeとして
        UPDATE_AVAILABLE reasonのheaderを返しleaderboard readを行わないことを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): filename matchを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): read未実行を観測するstub.
            sample_beatmap (Beatmap): filenameで見つかるbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: update availableのheader-only outcomeを検証して値を返さずに完了する.
        """
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
        """未認証viewerの依存categoryをheader-onlyにする契約を検証する.

        user IDなしのFRIENDS requestと取得可能なbeatmapを用意してresolveする.
        Observable outcomeとしてHEADERを返しtop row readを行わないことを確認する.

        Args:
            getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmap readを設定するstub.
            leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): read未実行を観測するstub.
            sample_beatmap (Beatmap): leaderboard対象のbeatmap fixture.
            sample_beatmapset (BeatmapSet): 対応するbeatmapset fixture.

        Returns:
            None: 未認証categoryのheader-only outcomeを検証して値を返さずに完了する.
        """
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
    """Viewer user IDをrequestへ付与してqueryを実行するtest harness.

    Attributes:
        query (BeatmapLeaderboardQuery): resolve対象のleaderboard query.
    """

    query: BeatmapLeaderboardQuery

    async def resolve(
        self,
        request: BeatmapLeaderboardRequest,
        *,
        user_id: int | None = None,
    ) -> BeatmapLeaderboardResult:
        """Viewer contextを付与したrequestをqueryへ渡す.

        Args:
            request (BeatmapLeaderboardRequest): viewer context以外を設定済みのrequest.
            user_id (int | None): requestへ付与するviewer user ID. 未認証時はNone.

        Returns:
            BeatmapLeaderboardResult: viewer contextを反映したquery result.
        """
        return await self.query.execute(replace(request, viewer_user_id=user_id))


def _query(
    getscores_repo: BeatmapScoreListingQueryRepositoryStub,
    leaderboard_repo: BeatmapLeaderboardQueryRepositoryStub,
    *,
    user_repo: ViewerUserQueryRepositoryStub | None = None,
    permission_service: ViewerPermissionServiceStub | None = None,
    friend_query: FriendEligibleUserIdsQueryStub | None = None,
) -> _BeatmapLeaderboardQueryHarness:
    """Score listingとleaderboard collaboratorを持つquery harnessを構成する.

    Args:
        getscores_repo (BeatmapScoreListingQueryRepositoryStub): beatmapとfetch stateを返すstub.
        leaderboard_repo (BeatmapLeaderboardQueryRepositoryStub): rowとpersonal bestを返すstub.
        user_repo (ViewerUserQueryRepositoryStub | None): viewer contextを返す任意のstub.
        permission_service (ViewerPermissionServiceStub | None): viewer permission用の任意stub.
        friend_query (FriendEligibleUserIdsQueryStub | None): Friends scopeを解決する任意のstub.

    Returns:
        _BeatmapLeaderboardQueryHarness: viewer user IDを渡してresolveできるharness.
    """
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
    """Legacy形式の入力値からleaderboard requestを組み立てる.

    Args:
        checksum_md5 (str): 対象beatmapのMD5 checksum.
        filename (str | None): checksum miss時に照合する任意のfilename.
        mode (int | None): Ruleset値へ変換するlegacy mode値.
        mods (int | None): ModCombinationへ変換するlegacy bitmask.
        leaderboard_type (int | None): LeaderboardCategoryへ変換するlegacy category値.
        song_select (bool | None): song select requestかを示す値.

    Returns:
        BeatmapLeaderboardRequest: header-only条件とscope情報を反映したrequest.
    """
    ruleset = _ruleset_from_mode(mode)
    category = _leaderboard_category_from_type(leaderboard_type)
    header_only = category is None or song_select is True
    selected_mods = None

    if mods is None:
        header_only = True
    else:
        mod_combination = ModCombination.from_bitmask(mods)
        if mod_combination.has(Mod.RELAX) or mod_combination.has(Mod.AUTOPILOT):
            header_only = True
        if category is LeaderboardCategory.SELECTED_MODS:
            selected_mods = mod_combination

    return BeatmapLeaderboardRequest(
        beatmap_checksum=checksum_md5,
        filename=filename,
        beatmapset_id_hint=5,
        viewer_user_id=None,
        ruleset=ruleset,
        playstyle=Playstyle.VANILLA,
        category=category,
        selected_mods=selected_mods,
        header_only=header_only,
    )


def _ruleset_from_mode(mode: int | None) -> Ruleset | None:
    """Legacy mode値を対応するRulesetへ変換する.

    Args:
        mode (int | None): legacy requestから受け取るmode値.

    Returns:
        Ruleset | None: 対応するRuleset. 値がないか未対応の場合はNone.
    """
    if mode is None:
        return None
    try:
        return Ruleset(mode)
    except ValueError:
        return None


def _leaderboard_category_from_type(
    leaderboard_type: int | None,
) -> LeaderboardCategory | None:
    """Legacy leaderboard typeを対応するcategoryへ変換する.

    Args:
        leaderboard_type (int | None): legacy requestから受け取るcategory値.

    Returns:
        LeaderboardCategory | None: 対応するcategory. 値がないか未対応の場合はNone.
    """
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
    """Assertion用の一貫したleaderboard rowを生成する.

    Args:
        score_id (int): 生成するscoreのID.
        user_id (int): rowに表示するuserのID.
        rank (int): leaderboard上の順位.

    Returns:
        BeatmapLeaderboardRow: 固定されたscore詳細を持つ順位行.
    """
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
    """Viewer userとpermissionを対応するstubへ登録する.

    Args:
        user_repo (ViewerUserQueryRepositoryStub): viewer userを保存するstub.
        permission_service (ViewerPermissionServiceStub): viewer permissionを保存するstub.
        user_id (int): 登録するviewerのuser ID.
        country (str): Country scopeに使うviewer country.
        permissions (Privileges): viewer visibilityのために設定するpermission.

    Returns:
        None: viewer contextをstubへ登録して値を返さずに完了する.
    """
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
