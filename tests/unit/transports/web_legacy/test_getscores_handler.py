"""Getscores handler metadata fetch and warmup behavior tests."""

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
    def __init__(self, result: LegacyWebAuthResult) -> None:
        self.result = result
        self.inputs: list[SessionCredentialsQueryInput] = []

    async def execute(
        self,
        input_data: SessionCredentialsQueryInput,
    ) -> SessionCredentialsQueryResult:
        self.inputs.append(input_data)
        return SessionCredentialsQueryResult(outcome=self.result)


@final
class _ScoreListingRepository:
    def __init__(self) -> None:
        self.beatmaps_by_checksum: dict[str, Beatmap] = {}
        self.beatmapsets_by_id: dict[int, BeatmapSet] = {}

    async def find_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        return self.beatmaps_by_checksum.get(checksum_md5)

    async def find_by_filename_in_beatmapset(
        self,
        beatmapset_id: int,
        original_filename: str,
    ) -> Beatmap | None:
        _ = (beatmapset_id, original_filename)
        return None

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        return self.beatmapsets_by_id.get(beatmapset_id)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        _ = target
        return None


@final
class _EmptyBeatmapLeaderboardRepository:
    async def list_top_rows(
        self,
        scope: LeaderboardReadScope,
        *,
        limit: int,
    ) -> tuple[BeatmapLeaderboardRow, ...]:
        _ = (scope, limit)
        return ()

    async def get_personal_best(
        self,
        scope: LeaderboardReadScope,
        *,
        viewer_user_id: int,
    ) -> BeatmapLeaderboardRow | None:
        _ = (scope, viewer_user_id)
        return None


class _RecordingBeatmapResolver:
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
        self.repository = repository
        self.beatmap = beatmap
        self.beatmapset = beatmapset
        self.calls = []

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
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
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool, float]] = []

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
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
    def __init__(
        self,
        repository: _ScoreListingRepository,
        beatmap: Beatmap,
        beatmapset: BeatmapSet,
        *,
        available_after_seconds: float,
    ) -> None:
        super().__init__(repository, beatmap, beatmapset)
        self.available_after_seconds = available_after_seconds

    @override
    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
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
    def __init__(self, outcome: BeatmapFileWarmupOutcome) -> None:
        self.outcome = outcome
        self.requests: list[BeatmapFileWarmupRequest] = []

    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult:
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
    return make_app_config().beatmap_default_bounded_wait_seconds


def _request(params: dict[str, str]) -> Request:
    return make_starlette_request(
        method="GET",
        path="/web/osu-osz2-getscores.php",
        query_params=params,
    )


def _query() -> dict[str, str]:
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
