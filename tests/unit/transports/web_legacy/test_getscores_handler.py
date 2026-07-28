"""GetscoresHandlerのmetadata resolve, authorization, file warmup contractを検証する."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, cast, final, override

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapEligibility,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSet,
    BeatmapSetResolveResult,
    BeatmapSourceVerification,
)
from osu_server.domain.identity.authentication import LegacyWebAuthFailure, LegacyWebAuthResult
from osu_server.services.commands.beatmaps import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupOutcome,
    BeatmapFileWarmupRequest,
    BeatmapFileWarmupResult,
    RequestBeatmapFileWarmupUseCase,
)
from osu_server.services.queries.identity import (
    SessionCredentialsQueryInput,
    SessionCredentialsQueryResult,
)
from osu_server.services.queries.scores import BeatmapLeaderboardQuery, BeatmapScoreListingQuery
from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
from osu_server.transports.stable.web_legacy.mappers import (
    GetscoresQueryParser,
    GetscoresStatusMapper,
)
from tests.factories.config import make_app_config
from tests.support.starlette_requests import make_starlette_request

if TYPE_CHECKING:
    from starlette.requests import Request

    from osu_server.domain.beatmaps import BeatmapFetchRecord, BeatmapFetchTarget
    from osu_server.repositories.interfaces.queries.beatmap_leaderboards import (
        BeatmapLeaderboardRow,
        LeaderboardReadScope,
    )
    from osu_server.services.queries.beatmaps.mirror import BeatmapMirrorService

_NOW = datetime(2026, 6, 15, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_CHECKSUM = "3b0aecd99eba50ffc7bff8da117d0e06"
_MENU_METADATA_AVAILABLE_AFTER_SECONDS = 1.0


@final
class _AuthQuery:
    """設定済みlegacy authentication outcomeを返すquery fakeを提供する.

    Attributes:
        result (LegacyWebAuthResult): executeが返すauthentication outcome.
        inputs (list[SessionCredentialsQueryInput]): executeへ渡されたcredential inputの順序.
    """

    def __init__(self, result: LegacyWebAuthResult) -> None:
        """返却するlegacy authentication outcomeを設定する.

        Args:
            result (LegacyWebAuthResult): handlerへ返すsuccessfulまたはfailed auth result.
        """
        self.result = result
        self.inputs: list[SessionCredentialsQueryInput] = []

    async def execute(
        self,
        input_data: SessionCredentialsQueryInput,
    ) -> SessionCredentialsQueryResult:
        """Credential inputを記録して設定済みauthentication outcomeを返す.

        Args:
            input_data (SessionCredentialsQueryInput): legacy credentialを持つquery input.

        Returns:
            SessionCredentialsQueryResult: 設定済みauth outcomeを包むquery result.
        """
        self.inputs.append(input_data)
        return SessionCredentialsQueryResult(outcome=self.result)


@final
class _ScoreListingRepository:
    """Checksumとbeatmapset IDでtest beatmap dataを保持するscore listing fakeを提供する.

    Attributes:
        beatmaps_by_checksum (dict[str, Beatmap]): checksumから解決するbeatmap mapping.
        beatmapsets_by_id (dict[int, BeatmapSet]): IDから解決するbeatmapset mapping.
    """

    def __init__(self) -> None:
        """Empty beatmapとbeatmapset mappingを初期化する."""
        self.beatmaps_by_checksum: dict[str, Beatmap] = {}
        self.beatmapsets_by_id: dict[int, BeatmapSet] = {}

    async def find_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """Checksumで保存済みbeatmapを取得する.

        Args:
            checksum_md5 (str): lookupするbeatmap checksum.

        Returns:
            Beatmap | None: 保存済みbeatmap. 不在ならNone.
        """
        return self.beatmaps_by_checksum.get(checksum_md5)

    async def find_by_filename_in_beatmapset(
        self,
        beatmapset_id: int,
        original_filename: str,
    ) -> Beatmap | None:
        """Filename fallbackを常にnot foundとして返す.

        Args:
            beatmapset_id (int): lookupを制限するbeatmapset ID.
            original_filename (str): lookupするoriginal osu file名.

        Returns:
            Beatmap | None: 常にNone. 本fakeはfilename indexを保持しない.
        """
        _ = (beatmapset_id, original_filename)
        return None

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """IDで保存済みbeatmapsetを取得する.

        Args:
            beatmapset_id (int): lookupするbeatmapset ID.

        Returns:
            BeatmapSet | None: 保存済みbeatmapset. 不在ならNone.
        """
        return self.beatmapsets_by_id.get(beatmapset_id)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Fetch state lookupを常にnot foundとして返す.

        Args:
            target (BeatmapFetchTarget): fetch stateを要求するbeatmap target.

        Returns:
            BeatmapFetchRecord | None: 常にNone. fetch stateを持たない状態を再現する.
        """
        _ = target
        return None


@final
class _EmptyBeatmapLeaderboardRepository:
    """Top rowとpersonal bestを返さないleaderboard repository fakeを提供する."""

    async def list_top_rows(
        self,
        scope: LeaderboardReadScope,
        *,
        limit: int,
    ) -> tuple[BeatmapLeaderboardRow, ...]:
        """Leaderboard top rowをempty tupleとして返す.

        Args:
            scope (LeaderboardReadScope): query対象のleaderboard scope.
            limit (int): 返却を要求する最大row数.

        Returns:
            tuple[BeatmapLeaderboardRow, ...]: 常にempty tuple. score rowなしを再現する.
        """
        _ = (scope, limit)
        return ()

    async def get_personal_best(
        self,
        scope: LeaderboardReadScope,
        *,
        viewer_user_id: int,
    ) -> BeatmapLeaderboardRow | None:
        """Viewerのpersonal bestをnot foundとして返す.

        Args:
            scope (LeaderboardReadScope): query対象のleaderboard scope.
            viewer_user_id (int): personal bestを要求するviewer user ID.

        Returns:
            BeatmapLeaderboardRow | None: 常にNone. personal bestなしを再現する.
        """
        _ = (scope, viewer_user_id)
        return None


class _RecordingBeatmapResolver:
    """Resolve callを記録して設定済みfresh beatmap resultを返すmirror resolver fakeを提供する.

    Attributes:
        repository (_ScoreListingRepository): resolve結果を保存するquery repository fake.
        beatmap (Beatmap): successful resolveで返すbeatmap.
        beatmapset (BeatmapSet): successful resolveで返すbeatmapset.
        calls (list[tuple[str, str, bool, float]]): resolve method, target, file requirement,
            wait値の順序.
    """

    repository: _ScoreListingRepository
    beatmap: Beatmap
    beatmapset: BeatmapSet
    calls: list[tuple[str, str, bool, float]]

    def __init__(
        self,
        repository: _ScoreListingRepository,
        beatmap: Beatmap,
        beatmapset: BeatmapSet,
    ) -> None:
        """Successful resolveで使うrepositoryとbeatmap dataを設定する.

        Args:
            repository (_ScoreListingRepository): resultを保存するrepository fake.
            beatmap (Beatmap): checksumまたはID resolveで返すbeatmap.
            beatmapset (BeatmapSet): checksumまたはID resolveで返すbeatmapset.
        """
        self.repository = repository
        self.beatmap = beatmap
        self.beatmapset = beatmapset
        self.calls = []

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Checksum resolveを記録してfresh beatmap resultを返す.

        Args:
            checksum_md5 (str): resolveするbeatmap checksum.
            options (BeatmapResolveOptions | None): file requirementとwaitを指定する
                optional resolve options.

        Returns:
            BeatmapResolveResult: 設定済みbeatmapとbeatmapsetを持つfresh result.
        """
        opts = options or BeatmapResolveOptions()
        self.calls.append(
            (
                "checksum",
                checksum_md5,
                opts.require_osu_file,
                opts.wait_timeout_seconds,
            )
        )
        self.repository.beatmaps_by_checksum[checksum_md5] = self.beatmap
        self.repository.beatmapsets_by_id[self.beatmapset.id] = self.beatmapset
        return _resolve_result(self.beatmap, self.beatmapset)

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Beatmap ID resolveを記録してfresh beatmap resultを返す.

        Args:
            beatmap_id (int): resolveするbeatmap ID.
            options (BeatmapResolveOptions | None): file requirementとwaitを指定する
                optional resolve options.

        Returns:
            BeatmapResolveResult: 設定済みbeatmapとbeatmapsetを持つfresh result.
        """
        opts = options or BeatmapResolveOptions()
        self.calls.append(
            (
                "beatmap_id",
                str(beatmap_id),
                opts.require_osu_file,
                opts.wait_timeout_seconds,
            )
        )
        return _resolve_result(self.beatmap, self.beatmapset)

    async def resolve_by_beatmapset_id(
        self,
        beatmapset_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapSetResolveResult:
        """Beatmapset ID resolveを記録してpending metadata resultを返す.

        Args:
            beatmapset_id (int): resolveするbeatmapset ID.
            options (BeatmapResolveOptions | None): file requirementとwaitを指定する
                optional resolve options.

        Returns:
            BeatmapSetResolveResult: beatmapsetなしのpending metadata result.
        """
        opts = options or BeatmapResolveOptions()
        self.calls.append(
            (
                "beatmapset_id",
                str(beatmapset_id),
                opts.require_osu_file,
                opts.wait_timeout_seconds,
            )
        )
        return BeatmapSetResolveResult(
            beatmapset=None,
            metadata_status=BeatmapFetchState.PENDING_FETCH,
            source=None,
            verified=False,
            last_fetched_at=None,
            next_refresh_at=None,
            reason="pending",
        )


@final
class _UnavailableBeatmapResolver:
    """Resolve callを記録してmetadata pending resultを返すmirror resolver fakeを提供する.

    Attributes:
        calls (list[tuple[str, str, bool, float]]): resolve method, target, file requirement,
            wait値の順序.
    """

    def __init__(self) -> None:
        """Empty resolve call記録を初期化する."""
        self.calls: list[tuple[str, str, bool, float]] = []

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Checksum resolveを記録してmetadata pending resultを返す.

        Args:
            checksum_md5 (str): resolveするbeatmap checksum.
            options (BeatmapResolveOptions | None): file requirementとwaitを指定する
                optional resolve options.

        Returns:
            BeatmapResolveResult: beatmapなしのpending metadata result.
        """
        opts = options or BeatmapResolveOptions()
        self.calls.append(
            (
                "checksum",
                checksum_md5,
                opts.require_osu_file,
                opts.wait_timeout_seconds,
            )
        )
        return _metadata_pending_result()

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Beatmap ID resolveを記録してmetadata pending resultを返す.

        Args:
            beatmap_id (int): resolveするbeatmap ID.
            options (BeatmapResolveOptions | None): file requirementとwaitを指定する
                optional resolve options.

        Returns:
            BeatmapResolveResult: beatmapなしのpending metadata result.
        """
        opts = options or BeatmapResolveOptions()
        self.calls.append(
            (
                "beatmap_id",
                str(beatmap_id),
                opts.require_osu_file,
                opts.wait_timeout_seconds,
            )
        )
        return _metadata_pending_result()

    async def resolve_by_beatmapset_id(
        self,
        beatmapset_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapSetResolveResult:
        """Beatmapset ID resolveを記録してpending metadata resultを返す.

        Args:
            beatmapset_id (int): resolveするbeatmapset ID.
            options (BeatmapResolveOptions | None): file requirementとwaitを指定する
                optional resolve options.

        Returns:
            BeatmapSetResolveResult: beatmapsetなしのpending metadata result.
        """
        opts = options or BeatmapResolveOptions()
        self.calls.append(
            (
                "beatmapset_id",
                str(beatmapset_id),
                opts.require_osu_file,
                opts.wait_timeout_seconds,
            )
        )
        return BeatmapSetResolveResult(
            beatmapset=None,
            metadata_status=BeatmapFetchState.PENDING_FETCH,
            source=None,
            verified=False,
            last_fetched_at=None,
            next_refresh_at=None,
            reason="pending",
        )


@final
class _DelayedBeatmapResolver(_RecordingBeatmapResolver):
    """Wait budgetが十分な場合だけfresh resultを返すdelayed resolver fakeを提供する.

    Attributes:
        available_after_seconds (float): metadataが利用可能になるまでの待機秒数.
    """

    def __init__(
        self,
        repository: _ScoreListingRepository,
        beatmap: Beatmap,
        beatmapset: BeatmapSet,
        *,
        available_after_seconds: float,
    ) -> None:
        """Successful dataとmetadata availability thresholdを設定する.

        Args:
            repository (_ScoreListingRepository): resultを保存するrepository fake.
            beatmap (Beatmap): metadata利用可能時に返すbeatmap.
            beatmapset (BeatmapSet): metadata利用可能時に返すbeatmapset.
            available_after_seconds (float): successful resolveに必要なwait秒数.
        """
        super().__init__(repository, beatmap, beatmapset)
        self.available_after_seconds = available_after_seconds

    @override
    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Checksum resolveのwait budgetに応じてpendingまたはfresh resultを返す.

        Args:
            checksum_md5 (str): resolveするbeatmap checksum.
            options (BeatmapResolveOptions | None): wait budgetを指定するoptional resolve options.

        Returns:
            BeatmapResolveResult: wait不足ならpending result. 十分ならfresh beatmap result.
        """
        opts = options or BeatmapResolveOptions()
        self.calls.append(
            (
                "checksum",
                checksum_md5,
                opts.require_osu_file,
                opts.wait_timeout_seconds,
            )
        )
        if opts.wait_timeout_seconds < self.available_after_seconds:
            return _metadata_pending_result()

        self.repository.beatmaps_by_checksum[checksum_md5] = self.beatmap
        self.repository.beatmapsets_by_id[self.beatmapset.id] = self.beatmapset
        return _resolve_result(self.beatmap, self.beatmapset)


@final
class _RecordingWarmupUseCase:
    """Warmup requestを記録して設定済みoutcomeを返すuse case fakeを提供する.

    Attributes:
        outcome (BeatmapFileWarmupOutcome): executeが返すwarmup outcome.
        requests (list[BeatmapFileWarmupRequest]): executeへ渡されたwarmup requestの順序.
    """

    def __init__(self, outcome: BeatmapFileWarmupOutcome) -> None:
        """返却するwarmup outcomeを設定する.

        Args:
            outcome (BeatmapFileWarmupOutcome): requestごとに返すwarmup outcome.
        """
        self.outcome = outcome
        self.requests: list[BeatmapFileWarmupRequest] = []

    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult:
        """Warmup requestを記録して設定済みoutcomeのresultを返す.

        Args:
            request (BeatmapFileWarmupRequest): stable Getscoresから発行されたwarmup request.

        Returns:
            BeatmapFileWarmupResult: request contextと設定済みoutcomeを持つresult.
        """
        self.requests.append(request)
        return BeatmapFileWarmupResult(
            outcome=self.outcome,
            entrance=request.entrance,
            user_id=request.user_id,
            beatmap_id=request.beatmap_id,
            checksum_md5=request.checksum_md5,
            reason="test",
        )


async def test_getscores_resolves_metadata_before_returning_not_found() -> None:
    """Getscoresがnot found response前にmetadata resolveとfile warmupを行うcontractを検証する.

    Returns:
        None: header response, checksum resolve, beatmap ID warmup requestを確認して完了する.
    """
    repository = _ScoreListingRepository()
    beatmap = _make_beatmap()
    beatmapset = _make_beatmapset(beatmap=beatmap)
    resolver = _RecordingBeatmapResolver(repository, beatmap, beatmapset)
    warmup = _RecordingWarmupUseCase(BeatmapFileWarmupOutcome.REQUESTED)
    handler = _make_handler(
        repository=repository,
        resolver=resolver,
        warmup=warmup,
        auth_result=LegacyWebAuthResult(user_id=2, username="PlayerOne"),
    )

    response = await handler(_request(_query()))

    assert response.status_code == HTTPStatus.OK
    assert bytes(response.body).split(b"\n")[0] == b"2|false|75|955866|0||"
    assert resolver.calls == [
        ("checksum", _CHECKSUM, False, _default_metadata_wait_seconds()),
    ]
    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_GETSCORES,
            user_id=2,
            beatmap_id=75,
        )
    ]


async def test_getscores_auth_failure_does_not_request_metadata_fetch() -> None:
    """Authentication failureがmetadata resolveとwarmupを開始しないcontractを検証する.

    Returns:
        None: HTTP 401, empty body, empty resolveとwarmup callを確認して完了する.
    """
    repository = _ScoreListingRepository()
    beatmap = _make_beatmap()
    beatmapset = _make_beatmapset(beatmap=beatmap)
    resolver = _RecordingBeatmapResolver(repository, beatmap, beatmapset)
    warmup = _RecordingWarmupUseCase(BeatmapFileWarmupOutcome.REQUESTED)
    handler = _make_handler(
        repository=repository,
        resolver=resolver,
        warmup=warmup,
        auth_result=LegacyWebAuthResult(failure=LegacyWebAuthFailure.INVALID_CREDENTIALS),
    )

    response = await handler(_request(_query()))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.body == b""
    assert resolver.calls == []
    assert warmup.requests == []


async def test_getscores_parse_failure_does_not_request_warmup() -> None:
    """Parse failureがmetadata resolveとwarmupを開始しないcontractを検証する.

    Returns:
        None: -1|false body, empty resolveとwarmup callを確認して完了する.
    """
    repository = _ScoreListingRepository()
    beatmap = _make_beatmap()
    beatmapset = _make_beatmapset(beatmap=beatmap)
    resolver = _RecordingBeatmapResolver(repository, beatmap, beatmapset)
    warmup = _RecordingWarmupUseCase(BeatmapFileWarmupOutcome.REQUESTED)
    handler = _make_handler(
        repository=repository,
        resolver=resolver,
        warmup=warmup,
        auth_result=LegacyWebAuthResult(user_id=2, username="PlayerOne"),
    )

    query = _query()
    _ = query.pop("c")
    _ = query.pop("f")
    _ = query.pop("i")
    response = await handler(_request(query))

    assert response.status_code == HTTPStatus.OK
    assert response.body == b"-1|false"
    assert resolver.calls == []
    assert warmup.requests == []


async def test_getscores_unavailable_uses_parsed_checksum_for_warmup() -> None:
    """Unavailable metadata resultがparsed checksumをwarmupへ渡すcontractを検証する.

    Returns:
        None: -1|false bodyとchecksum scoped warmup requestを確認して完了する.
    """
    repository = _ScoreListingRepository()
    resolver = _UnavailableBeatmapResolver()
    warmup = _RecordingWarmupUseCase(BeatmapFileWarmupOutcome.METADATA_PENDING)
    handler = _make_handler(
        repository=repository,
        resolver=resolver,
        warmup=warmup,
        auth_result=LegacyWebAuthResult(user_id=2, username="PlayerOne"),
    )

    response = await handler(_request(_query()))

    assert response.status_code == HTTPStatus.OK
    assert response.body == b"-1|false"
    assert resolver.calls == [
        ("checksum", _CHECKSUM, False, _default_metadata_wait_seconds()),
    ]
    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_GETSCORES,
            user_id=2,
            checksum_md5=_CHECKSUM,
        )
    ]


async def test_getscores_warmup_failure_does_not_change_response_body() -> None:
    """Warmup failureがsuccessful Getscores response bodyを変えないcontractを検証する.

    Returns:
        None: header responseと記録済みfailed warmup requestを確認して完了する.
    """
    repository = _ScoreListingRepository()
    beatmap = _make_beatmap()
    beatmapset = _make_beatmapset(beatmap=beatmap)
    resolver = _RecordingBeatmapResolver(repository, beatmap, beatmapset)
    warmup = _RecordingWarmupUseCase(BeatmapFileWarmupOutcome.FAILED)
    handler = _make_handler(
        repository=repository,
        resolver=resolver,
        warmup=warmup,
        auth_result=LegacyWebAuthResult(user_id=2, username="PlayerOne"),
    )

    response = await handler(_request(_query()))

    assert response.status_code == HTTPStatus.OK
    assert bytes(response.body).split(b"\n")[0] == b"2|false|75|955866|0||"
    assert warmup.requests == [
        BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_GETSCORES,
            user_id=2,
            beatmap_id=75,
        )
    ]


async def test_getscores_default_wait_covers_menu_transition_metadata_fetch() -> None:
    """Default metadata waitがmenu transition中のavailability thresholdをcoverする.

    Returns:
        None: delayed resolverがfresh header responseを返すことを確認して完了する.
    """
    repository = _ScoreListingRepository()
    beatmap = _make_beatmap()
    beatmapset = _make_beatmapset(beatmap=beatmap)
    resolver = _DelayedBeatmapResolver(
        repository,
        beatmap,
        beatmapset,
        available_after_seconds=_MENU_METADATA_AVAILABLE_AFTER_SECONDS,
    )
    warmup = _RecordingWarmupUseCase(BeatmapFileWarmupOutcome.REQUESTED)
    handler = _make_handler(
        repository=repository,
        resolver=resolver,
        warmup=warmup,
        auth_result=LegacyWebAuthResult(user_id=2, username="PlayerOne"),
    )

    response = await handler(_request(_query()))

    assert response.status_code == HTTPStatus.OK
    assert bytes(response.body).split(b"\n")[0] == b"2|false|75|955866|0||"
    assert resolver.calls == [
        ("checksum", _CHECKSUM, False, _default_metadata_wait_seconds()),
    ]


def _make_handler(
    *,
    repository: _ScoreListingRepository,
    resolver: object,
    warmup: _RecordingWarmupUseCase,
    auth_result: LegacyWebAuthResult,
    beatmap_metadata_wait_seconds: float | None = None,
) -> GetscoresHandler:
    """Typed fake依存を注入したGetscoresHandlerを構築する.

    Args:
        repository (_ScoreListingRepository): score listing queryへ渡すrepository fake.
        resolver (object): BeatmapMirrorServiceとしてcastするresolver fake.
        warmup (_RecordingWarmupUseCase): file warmup requestを記録するuse case fake.
        auth_result (LegacyWebAuthResult): handler auth queryが返すauthentication outcome.
        beatmap_metadata_wait_seconds (float | None): optional bounded metadata wait.
            Noneならconfig既定値.

    Returns:
        GetscoresHandler: legacy Getscores requestを処理するhandler fixture.
    """
    return GetscoresHandler(
        auth_query=_AuthQuery(auth_result),
        getscores_parser=GetscoresQueryParser(),
        getscores_query=BeatmapScoreListingQuery(
            BeatmapLeaderboardQuery(
                repository,
                _EmptyBeatmapLeaderboardRepository(),
            )
        ),
        status_mapper=GetscoresStatusMapper(),
        beatmap_resolver=cast("BeatmapMirrorService", resolver),
        beatmap_file_warmup=cast(
            "RequestBeatmapFileWarmupUseCase",
            cast("object", warmup),
        ),
        beatmap_metadata_wait_seconds=(
            _default_metadata_wait_seconds()
            if beatmap_metadata_wait_seconds is None
            else beatmap_metadata_wait_seconds
        ),
    )


def _default_metadata_wait_seconds() -> float:
    """AppConfigからGetscores metadata resolve用の既定wait秒数を取得する.

    Returns:
        float: bounded beatmap metadata waitの設定値.
    """
    return make_app_config().beatmap_default_bounded_wait_seconds


def _request(params: dict[str, str]) -> Request:
    """Getscores endpointへ送るStarlette GET requestを構築する.

    Args:
        params (dict[str, str]): query stringへ設定するlegacy Getscores parameter mapping.

    Returns:
        Request: osu-osz2-getscores.php pathを持つStarlette request.
    """
    return make_starlette_request(
        method="GET",
        path="/web/osu-osz2-getscores.php",
        query_params=params,
    )


def _query() -> dict[str, str]:
    """Successful Getscores requestを表す既定query parameter mappingを構築する.

    Returns:
        dict[str, str]: checksum, filename, mode, credentialを含むlegacy query mapping.
    """
    return {
        "s": "0",
        "vv": "4",
        "v": "1",
        "c": _CHECKSUM,
        "f": "KIRA & Heartbreaker - B.B.F (hypercyte) [Hard].osu",
        "m": "0",
        "i": "955866",
        "mods": "0",
        "h": "",
        "a": "0",
        "us": "PlayerOne",
        "ha": "cccccccccccccccccccccccccccccccc",
    }


def _make_beatmap() -> Beatmap:
    """Fresh ranked metadataを持つGetscores handler用beatmap fixtureを構築する.

    Returns:
        Beatmap: checksumとmissing osu file stateを持つranked beatmap.
    """
    return Beatmap(
        id=75,
        beatmapset_id=955866,
        checksum_md5=_CHECKSUM,
        mode=BeatmapMode.OSU,
        version="Hard",
        total_length=240,
        hit_length=220,
        max_combo=1234,
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
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _make_beatmapset(*, beatmap: Beatmap) -> BeatmapSet:
    """指定beatmapを含むGetscores handler用beatmapset fixtureを構築する.

    Args:
        beatmap (Beatmap): beatmapsetのbeatmapsへ設定するresolved beatmap.

    Returns:
        BeatmapSet: ranked metadataと指定beatmapを持つbeatmapset.
    """
    return BeatmapSet(
        id=955866,
        artist="KIRA & Heartbreaker",
        title="B.B.F",
        creator="hypercyte",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _resolve_result(beatmap: Beatmap, beatmapset: BeatmapSet) -> BeatmapResolveResult:
    """Fresh metadataが利用可能なsuccessful beatmap resolve resultを構築する.

    Args:
        beatmap (Beatmap): successful resultへ設定するresolved beatmap.
        beatmapset (BeatmapSet): successful resultへ設定するresolved beatmapset.

    Returns:
        BeatmapResolveResult: eligibleでfresh metadataを持つresolve result.
    """
    return BeatmapResolveResult(
        beatmap=beatmap,
        beatmapset=beatmapset,
        eligibility=BeatmapEligibility(
            accepts_scores=True,
            has_leaderboard=True,
            awards_ranked_pp=True,
            awards_loved_pp=False,
            requires_osu_file_for_pp=True,
            is_officially_verified=True,
            is_mirror_derived=False,
            accepts_failed_scores=True,
            failed_scores_have_leaderboard=True,
            failed_scores_update_best_score=False,
            failed_scores_award_ranked_pp=False,
            failed_scores_award_loved_pp=False,
            denial_reason=None,
        ),
        metadata_status=BeatmapFetchState.FRESH,
        file_status=beatmap.file_state,
        source=beatmap.official_status_source,
        verified=True,
        last_fetched_at=beatmap.last_fetched_at,
        next_refresh_at=beatmap.next_refresh_at,
        reason="test",
    )


def _metadata_pending_result() -> BeatmapResolveResult:
    """Beatmap dataなしのmetadata pending resolve resultを構築する.

    Returns:
        BeatmapResolveResult: pending fetch stateとmissing file stateを持つresult.
    """
    return BeatmapResolveResult(
        beatmap=None,
        beatmapset=None,
        eligibility=None,
        metadata_status=BeatmapFetchState.PENDING_FETCH,
        file_status=BeatmapFileState.MISSING,
        source=None,
        verified=False,
        last_fetched_at=None,
        next_refresh_at=None,
        reason="pending",
    )
