"""Stable osu!direct endpointのHTTP contractを検証するmodule."""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from starlette.testclient import TestClient
from tests.support.app import resolve_dependency
from tests.support.credentials import FIXED_TEST_PASSWORD_MD5
from tests.support.persistence import seed_user

from osu_server.app import create_app as create_runtime_app
from osu_server.composition.providers.test import (
    TestProviderSet,
    make_in_memory_runtime_provider_set,
    replace_value,
)
from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapResolveResult,
    BeatmapSet,
    BeatmapSetResolveResult,
    BeatmapSourceVerification,
    DirectPointLookupTargetKind,
    DirectSearchRequest,
)
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.queries.beatmaps import (
    DirectPointLookupQuery,
    DirectSearchQuery,
    DirectSearchQueryResult,
)
from osu_server.services.queries.identity.password_service import PasswordService

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from dishka import Provider
    from starlette.applications import Starlette

    from osu_server.domain.beatmaps import (
        BeatmapResolveOptions,
    )

_NOW = datetime(2026, 8, 10, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_TEST_USERNAME = "DirectUser"
_BEATMAPSET_ID = 12_345
_BEATMAP_ID = 54_321
_KNOWN_CHECKSUM = "0123456789abcdef0123456789abcdef"
_POINT_LOOKUP_WAIT_SECONDS = 0.25


@dataclass(slots=True)
class _DirectSearchQueryFake:
    """Endpoint contract用に固定direct search resultを返すquery fake.

    Attributes:
        result (DirectSearchQueryResult): executeが返す固定search結果.
        inputs (list[DirectSearchRequest]): endpointから渡されたsearch request履歴.
    """

    result: DirectSearchQueryResult
    inputs: list[DirectSearchRequest]

    async def execute(self, request: DirectSearchRequest) -> DirectSearchQueryResult:
        """Search requestを記録して固定resultを返す.

        Args:
            request (DirectSearchRequest): stable endpointが作成したsearch request.

        Returns:
            DirectSearchQueryResult: testごとに指定したstable-ready検索結果.
        """
        self.inputs.append(request)
        return self.result


@dataclass(slots=True, frozen=True)
class _PointLookupCall:
    """Point lookup resolver fakeへ渡されたtargetとwait上限を保持する.

    Attributes:
        kind (DirectPointLookupTargetKind): 呼び出されたlookup target種別.
        value (int | str): 呼び出されたlookup target値.
        wait_timeout_seconds (float | None): resolverへ渡されたbounded wait秒数.
    """

    kind: DirectPointLookupTargetKind
    value: int | str
    wait_timeout_seconds: float | None


@dataclass(slots=True)
class _DirectPointLookupResolverFake:
    """Direct point lookup queryに渡すcache-first resolver fake.

    Attributes:
        beatmapset (BeatmapSet | None): 解決済みとして返すbeatmapset. Noneならmissにする.
        calls (list[_PointLookupCall]): resolver methodの呼び出し履歴.
    """

    beatmapset: BeatmapSet | None
    calls: list[_PointLookupCall]

    async def resolve_by_beatmapset_id(
        self,
        beatmapset_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapSetResolveResult:
        """Beatmapset ID lookupを記録して固定resultを返す.

        Args:
            beatmapset_id (int): endpointからparseされたbeatmapset ID.
            options (BeatmapResolveOptions | None): direct queryが設定したbounded wait.

        Returns:
            BeatmapSetResolveResult: 固定beatmapsetまたは未解決result.
        """
        self.calls.append(
            _PointLookupCall(
                DirectPointLookupTargetKind.BEATMAPSET_ID,
                beatmapset_id,
                _wait_timeout_seconds(options),
            )
        )
        return _beatmapset_result(self.beatmapset)

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Beatmap ID lookupを記録して固定resultを返す.

        Args:
            beatmap_id (int): endpointからparseされたbeatmap ID.
            options (BeatmapResolveOptions | None): direct queryが設定したbounded wait.

        Returns:
            BeatmapResolveResult: 固定beatmapsetのchildまたは未解決result.
        """
        self.calls.append(
            _PointLookupCall(
                DirectPointLookupTargetKind.BEATMAP_ID,
                beatmap_id,
                _wait_timeout_seconds(options),
            )
        )
        return _beatmap_result(self.beatmapset)

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Checksum lookupを記録して固定resultを返す.

        Args:
            checksum_md5 (str): endpointからparseされたMD5 checksum.
            options (BeatmapResolveOptions | None): direct queryが設定したbounded wait.

        Returns:
            BeatmapResolveResult: 固定beatmapsetのchildまたは未解決result.
        """
        self.calls.append(
            _PointLookupCall(
                DirectPointLookupTargetKind.CHECKSUM,
                checksum_md5,
                _wait_timeout_seconds(options),
            )
        )
        return _beatmap_result(self.beatmapset)


def test_direct_search_route_returns_count_and_stable_rows_for_authenticated_user(
    tmp_path: Path,
) -> None:
    """認証済みdirect search endpointがcount lineとstable rowを返す契約を検証する.

    Args:
        tmp_path (Path): in-memory app用blob storageを隔離するtemporary directory.

    Returns:
        None: HTTP 200 responseとstable row fieldを検証して完了する.
    """
    beatmapset = _beatmapset()
    search_query = _DirectSearchQueryFake(DirectSearchQueryResult((beatmapset,), 1), [])
    with _test_env():
        app = _create_app(tmp_path / "blobs", search_query=search_query)
        with TestClient(app, raise_server_exceptions=False) as client:
            user_id = asyncio.run(_seed_authenticated_user(app))
            response = client.get(
                "http://osu.athena.localhost/web/osu-search.php",
                params=_search_params(q="Camellia", r="4"),
            )

    assert response.status_code == HTTPStatus.OK
    lines = response.text.splitlines()
    row_fields = lines[1].split("|")
    assert lines[0] == "1"
    assert len(row_fields) == 15
    assert row_fields[0] == f"{_BEATMAPSET_ID} Camellia - Direct Contract.osz"
    assert row_fields[7] == str(_BEATMAPSET_ID)
    assert row_fields[13] == "Normal@0"
    assert len(search_query.inputs) == 1
    assert search_query.inputs[0].authenticated_user_id == user_id
    assert search_query.inputs[0].query_text == "Camellia"


def test_direct_point_lookup_route_resolves_by_set_beatmap_and_checksum(
    tmp_path: Path,
) -> None:
    """Point lookup endpointが`s`,`b`,`c`から同じstable rowを返す契約を検証する.

    Args:
        tmp_path (Path): in-memory app用blob storageを隔離するtemporary directory.

    Returns:
        None: 各targetのHTTP 200 responseとresolver呼び出しを検証して完了する.
    """
    resolver = _DirectPointLookupResolverFake(_beatmapset(), [])
    with _test_env():
        app = _create_app(
            tmp_path / "blobs",
            point_lookup_query=DirectPointLookupQuery(
                resolver,
                bounded_wait_seconds=_POINT_LOOKUP_WAIT_SECONDS,
            ),
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            _ = asyncio.run(_seed_authenticated_user(app))
            responses = (
                client.get(
                    "http://osu.athena.localhost/web/osu-search-set.php",
                    params=_lookup_params(s=str(_BEATMAPSET_ID)),
                ),
                client.get(
                    "http://osu.athena.localhost/web/osu-search-set.php",
                    params=_lookup_params(b=str(_BEATMAP_ID)),
                ),
                client.get(
                    "http://osu.athena.localhost/web/osu-search-set.php",
                    params=_lookup_params(c=_KNOWN_CHECKSUM),
                ),
            )

    assert [response.status_code for response in responses] == [HTTPStatus.OK] * 3
    assert {response.text for response in responses} == {_stable_row_text()}
    assert resolver.calls == [
        _PointLookupCall(
            DirectPointLookupTargetKind.BEATMAPSET_ID,
            _BEATMAPSET_ID,
            _POINT_LOOKUP_WAIT_SECONDS,
        ),
        _PointLookupCall(
            DirectPointLookupTargetKind.BEATMAP_ID,
            _BEATMAP_ID,
            _POINT_LOOKUP_WAIT_SECONDS,
        ),
        _PointLookupCall(
            DirectPointLookupTargetKind.CHECKSUM,
            _KNOWN_CHECKSUM,
            _POINT_LOOKUP_WAIT_SECONDS,
        ),
    ]


def test_direct_routes_do_not_expose_catalog_data_when_unauthenticated_or_denied(
    tmp_path: Path,
) -> None:
    """認証失敗とpolicy拒否でdirect endpointがcatalog dataを返さない契約を検証する.

    Args:
        tmp_path (Path): in-memory app用blob storageを隔離するtemporary directory.

    Returns:
        None: searchとpoint lookupの拒否responseが空bodyでwork未実行なことを検証する.
    """
    unauth_search = _DirectSearchQueryFake(DirectSearchQueryResult((_beatmapset(),), 1), [])
    unauth_resolver = _DirectPointLookupResolverFake(_beatmapset(), [])
    with _test_env():
        app = _create_app(
            tmp_path / "unauth-blobs",
            search_query=unauth_search,
            point_lookup_query=DirectPointLookupQuery(unauth_resolver),
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            unauth_search_response = client.get(
                "http://osu.athena.localhost/web/osu-search.php",
                params={"q": "Camellia"},
            )
            unauth_lookup_response = client.get(
                "http://osu.athena.localhost/web/osu-search-set.php",
                params={"s": str(_BEATMAPSET_ID)},
            )

    denied_search = _DirectSearchQueryFake(DirectSearchQueryResult((_beatmapset(),), 1), [])
    denied_resolver = _DirectPointLookupResolverFake(_beatmapset(), [])
    with _test_env(access_policy="disabled"):
        app = _create_app(
            tmp_path / "denied-blobs",
            search_query=denied_search,
            point_lookup_query=DirectPointLookupQuery(denied_resolver),
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            _ = asyncio.run(_seed_authenticated_user(app))
            denied_search_response = client.get(
                "http://osu.athena.localhost/web/osu-search.php",
                params=_search_params(q="Camellia"),
            )
            denied_lookup_response = client.get(
                "http://osu.athena.localhost/web/osu-search-set.php",
                params=_lookup_params(s=str(_BEATMAPSET_ID)),
            )

    assert unauth_search_response.status_code == HTTPStatus.UNAUTHORIZED
    assert unauth_search_response.content == b""
    assert unauth_lookup_response.status_code == HTTPStatus.UNAUTHORIZED
    assert unauth_lookup_response.content == b""
    assert unauth_search.inputs == []
    assert unauth_resolver.calls == []

    assert denied_search_response.status_code == HTTPStatus.UNAUTHORIZED
    assert denied_search_response.content == b""
    assert denied_lookup_response.status_code == HTTPStatus.UNAUTHORIZED
    assert denied_lookup_response.content == b""
    assert denied_search.inputs == []
    assert denied_resolver.calls == []


def test_direct_point_lookup_miss_returns_200_empty_body_with_bounded_wait(
    tmp_path: Path,
) -> None:
    """未解決point lookupがbounded wait付きでHTTP 200空bodyになる契約を検証する.

    Args:
        tmp_path (Path): in-memory app用blob storageを隔離するtemporary directory.

    Returns:
        None: resolverへwait上限が渡り, endpointは空bodyを返すことを検証する.
    """
    resolver = _DirectPointLookupResolverFake(None, [])
    with _test_env():
        app = _create_app(
            tmp_path / "blobs",
            point_lookup_query=DirectPointLookupQuery(
                resolver,
                bounded_wait_seconds=_POINT_LOOKUP_WAIT_SECONDS,
            ),
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            _ = asyncio.run(_seed_authenticated_user(app))
            response = client.get(
                "http://osu.athena.localhost/web/osu-search-set.php",
                params=_lookup_params(s="999999"),
            )

    assert response.status_code == HTTPStatus.OK
    assert response.content == b""
    assert resolver.calls == [
        _PointLookupCall(
            DirectPointLookupTargetKind.BEATMAPSET_ID,
            999_999,
            _POINT_LOOKUP_WAIT_SECONDS,
        )
    ]


def test_direct_route_addition_preserves_existing_stable_web_routes(tmp_path: Path) -> None:
    """Direct route追加後も既存getscores routeがweb legacy hostで残る契約を検証する.

    Args:
        tmp_path (Path): in-memory app用blob storageを隔離するtemporary directory.

    Returns:
        None: getscores routeが404にならず既存のauth failure responseを返すことを検証する.
    """
    with _test_env():
        app = _create_app(tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("http://osu.athena.localhost/web/osu-osz2-getscores.php")

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.content == b""


@contextmanager
def _test_env(*, access_policy: str = "authenticated") -> Generator[None]:
    """Endpoint contract test用の環境変数を一時的に設定する.

    Args:
        access_policy (str): `OSU_DIRECT_ACCESS_POLICY`へ設定するpolicy値.

    Yields:
        None: test用環境変数を設定したblockを実行する.

    Notes:
        context終了時に変更した環境変数は呼出前の値へ復元する.
    """
    keys = (
        "ENVIRONMENT",
        "DOMAIN",
        "DATABASE_URL",
        "VALKEY_URL",
        "OSU_DIRECT_ACCESS_POLICY",
    )
    old_values = {key: os.environ.get(key) for key in keys}
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DOMAIN"] = "athena.localhost"
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://user:pass@localhost/athena"
    os.environ["VALKEY_URL"] = "redis://localhost:6379/0"
    os.environ["OSU_DIRECT_ACCESS_POLICY"] = access_policy
    try:
        yield
    finally:
        for key, old_value in old_values.items():
            if old_value is None:
                _ = os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def _create_app(
    blob_root: Path,
    *,
    search_query: _DirectSearchQueryFake | None = None,
    point_lookup_query: DirectPointLookupQuery | None = None,
) -> Starlette:
    """Direct endpoint contract用のin-memory applicationを作成する.

    Args:
        blob_root (Path): test用blob storage root.
        search_query (_DirectSearchQueryFake | None): direct search use-case replacement.
        point_lookup_query (DirectPointLookupQuery | None): point lookup use-case replacement.

    Returns:
        Starlette: direct routeを本物のhandlerで処理するtest application.
    """
    direct_search_query = search_query or _DirectSearchQueryFake(
        DirectSearchQueryResult(beatmapsets=(), stable_result_count=0),
        [],
    )
    direct_point_lookup_query = point_lookup_query or DirectPointLookupQuery(
        _DirectPointLookupResolverFake(None, [])
    )
    overrides: tuple[Provider, ...] = (
        make_in_memory_runtime_provider_set(blob_root=blob_root),
        TestProviderSet(
            replace_value(
                DirectSearchQuery,
                cast("DirectSearchQuery", cast("object", direct_search_query)),
            ),
            replace_value(DirectPointLookupQuery, direct_point_lookup_query),
        ),
    )
    return create_runtime_app(provider_overrides=overrides)


async def _seed_authenticated_user(app: Starlette) -> int:
    """Legacy credentialとactive sessionを持つdirect test userをseedする.

    Args:
        app (Starlette): lifespan開始済みのin-memory application.

    Returns:
        int: 作成した認証済みuser ID.
    """
    password_service = await resolve_dependency(app, PasswordService)
    password_hash = await password_service.hash(FIXED_TEST_PASSWORD_MD5)
    user = await seed_user(
        app,
        User(
            id=0,
            username=_TEST_USERNAME,
            safe_username=User.normalize_username(_TEST_USERNAME),
            email="direct-user@example.com",
            password_hash=password_hash,
            country="JP",
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    session_store = await resolve_dependency(app, SessionStore)
    await session_store.create(
        user.id,
        "direct-endpoint-contract-session",
        data=SessionData(
            user_id=user.id,
            username=user.username,
            privileges=int(Privileges.NORMAL),
            country=user.country,
            osu_version="b20260810",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
        ),
    )
    return user.id


def _search_params(**overrides: str) -> dict[str, str]:
    """認証済みdirect search用query parameterを構築する.

    Args:
        **overrides (str): 既定値を置換するquery parameter.

    Returns:
        dict[str, str]: `u`,`h`,`q`,`r`,`m`,`p`を持つquery parameter.
    """
    params = {
        "u": _TEST_USERNAME,
        "h": FIXED_TEST_PASSWORD_MD5,
        "q": "",
        "r": "4",
        "m": "0",
        "p": "0",
    }
    params.update(overrides)
    return params


def _lookup_params(**target: str) -> dict[str, str]:
    """認証済みdirect point lookup用query parameterを構築する.

    Args:
        **target (str): `s`,`b`,`c`のいずれかを持つlookup target.

    Returns:
        dict[str, str]: `u`,`h`とtargetを持つquery parameter.
    """
    params = {
        "u": _TEST_USERNAME,
        "h": FIXED_TEST_PASSWORD_MD5,
    }
    params.update(target)
    return params


def _beatmapset() -> BeatmapSet:
    """Stable direct rowへ変換可能なranked beatmapsetを作成する.

    Returns:
        BeatmapSet: checksum, child beatmap, metadata時刻を持つtest beatmapset.
    """
    beatmap = Beatmap(
        id=_BEATMAP_ID,
        beatmapset_id=_BEATMAPSET_ID,
        checksum_md5=_KNOWN_CHECKSUM,
        mode=BeatmapMode.OSU,
        version="Normal",
        total_length=120,
        hit_length=110,
        max_combo=500,
        bpm=180.0,
        cs=4.0,
        od=8.0,
        ar=9.0,
        hp=6.0,
        difficulty_rating=2.5,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
        official_last_updated_at=_NOW,
    )
    return BeatmapSet(
        id=_BEATMAPSET_ID,
        artist="Camellia",
        title="Direct Contract",
        creator="ContractMapper",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _stable_row_text() -> str:
    """Direct test beatmapsetのstable row本文を返す.

    Returns:
        str: formatterから期待されるsingle-row stable direct body.
    """
    return (
        f"{_BEATMAPSET_ID} Camellia - Direct Contract.osz"
        "|Camellia"
        "|Direct Contract"
        "|ContractMapper"
        "|2"
        "|0.0"
        "|2026-08-10 00:00:00"
        f"|{_BEATMAPSET_ID}"
        "|0"
        "|0"
        "|0"
        "|0"
        "|0"
        "|Normal@0"
        "|0"
    )


def _wait_timeout_seconds(options: BeatmapResolveOptions | None) -> float | None:
    """Resolver optionからwait上限だけを抽出する.

    Args:
        options (BeatmapResolveOptions | None): direct queryから渡されたresolver option.

    Returns:
        float | None: optionがある場合はwait_timeout_seconds, ない場合はNone.
    """
    return options.wait_timeout_seconds if options is not None else None


def _beatmapset_result(beatmapset: BeatmapSet | None) -> BeatmapSetResolveResult:
    """Beatmapset resolver用の固定resultを作成する.

    Args:
        beatmapset (BeatmapSet | None): 解決済みとして返すbeatmapset.

    Returns:
        BeatmapSetResolveResult: direct point lookup queryが消費するresolver result.
    """
    return BeatmapSetResolveResult(
        beatmapset=beatmapset,
        metadata_status=BeatmapFetchState.FRESH
        if beatmapset is not None
        else BeatmapFetchState.PENDING_FETCH,
        source=BeatmapMetadataSource.OFFICIAL if beatmapset is not None else None,
        verified=beatmapset is not None,
        last_fetched_at=_NOW if beatmapset is not None else None,
        next_refresh_at=_NEXT_REFRESH if beatmapset is not None else None,
        reason=None if beatmapset is not None else "pending",
    )


def _beatmap_result(beatmapset: BeatmapSet | None) -> BeatmapResolveResult:
    """Beatmap resolver用の固定resultを作成する.

    Args:
        beatmapset (BeatmapSet | None): 解決済みとして返すbeatmapset.

    Returns:
        BeatmapResolveResult: direct point lookup queryが消費するresolver result.
    """
    beatmap = beatmapset.beatmaps[0] if beatmapset is not None else None
    return BeatmapResolveResult(
        beatmap=beatmap,
        beatmapset=beatmapset,
        eligibility=None,
        metadata_status=BeatmapFetchState.FRESH
        if beatmapset is not None
        else BeatmapFetchState.PENDING_FETCH,
        file_status=BeatmapFileState.MISSING,
        source=BeatmapMetadataSource.OFFICIAL if beatmapset is not None else None,
        verified=beatmapset is not None,
        last_fetched_at=_NOW if beatmapset is not None else None,
        next_refresh_at=_NEXT_REFRESH if beatmapset is not None else None,
        reason=None if beatmapset is not None else "pending",
    )
