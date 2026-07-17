"""E2E validation for getscores unavailable / update / auth / parse-only paths.

Task 5.2 closure — exercises every short-response and update-available branch
end-to-end and confirms that parse-only controls (m, mods, s, v, vv) do not
vary the MVP header output, including converted-mode fixture requests.

Coverage complements ``test_getscores_endpoint.py`` (routing, auth basics,
known checksum) and ``test_getscores_status_fixtures.py`` (submitted-status
header bodies) by adding:

* NotSubmitted official status -> ``-1|false``
* mirror returns PENDING_FETCH -> ``-1|false``
* mirror returns FAILED metadata -> ``-1|false``
* UpdateAvailable end-to-end body bytes (``1|false``)
* Parse-only control invariance over the known-header response
* Converted-mode fixture iteration produces the same wire status
* Invalid credentials and no-session 401 with empty body (regression guard)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from athena_cli.stable_verification.getscores_evidence import (
    GetscoresWireShapeId,
    load_getscores_completion_evidence,
)
from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileAttachment,
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.commands.beatmaps import RequestBeatmapFileWarmupUseCase
from osu_server.services.queries.beatmaps.mirror import BeatmapMirrorService
from osu_server.services.queries.identity.password_service import PasswordService
from tests.support.app import create_in_memory_app as create_app
from tests.support.app import resolve_dependency
from tests.support.getscores_contract import (
    build_getscores_contract_query,
    read_getscores_expected_body,
)
from tests.support.persistence import (
    attach_beatmap_file,
    seed_beatmap_fetch_state,
    seed_beatmapset,
    seed_user,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    import httpx2
    from starlette.applications import Starlette

    from osu_server.domain.beatmaps import BeatmapResolveOptions, BeatmapResolveResult
    from osu_server.services.commands.beatmaps import (
        BeatmapFileWarmupRequest,
        BeatmapFileWarmupResult,
    )


_TEST_USERNAME = "StableUser"
_TEST_PASSWORD_PLAIN = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD_PLAIN.encode()).hexdigest()
_KNOWN_CHECKSUM = "0123456789abcdef0123456789abcdef"
_UNKNOWN_CHECKSUM = "f" * 32
_UPDATE_FILENAME = "Camellia - Exit (Realazy) [Insane].osu"
_FIXTURE_CHECKSUM = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
_FIXTURE_SET_ID = 1
_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)

_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
_GETSCORES_MANIFEST_ROOT = _FIXTURE_ROOT / "stable_compatibility" / "getscores"
_GETSCORES_BODY_ROOT = _FIXTURE_ROOT / "web_legacy" / "getscores" / "completion"
_GETSCORES_EVIDENCE = load_getscores_completion_evidence(
    _GETSCORES_MANIFEST_ROOT,
    _GETSCORES_BODY_ROOT,
)
_GETSCORES_CASES = {case.case_id: case for case in _GETSCORES_EVIDENCE.branch_cases}
_GETSCORES_SHAPES = {shape.shape_id: shape for shape in _GETSCORES_EVIDENCE.response_shapes}

_CONVERTED_FIXTURE_PATH = (
    _FIXTURE_ROOT / "web_legacy" / "getscores" / "converted_mode_requests.json"
)


@contextmanager
def _test_env() -> Generator[None]:
    old_env = os.environ.get("ENVIRONMENT")
    old_domain = os.environ.get("DOMAIN")
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DOMAIN"] = "athena.localhost"
    _ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
    _ = os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")
    try:
        yield
    finally:
        if old_env is None:
            _ = os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = old_env
        if old_domain is None:
            _ = os.environ.pop("DOMAIN", None)
        else:
            os.environ["DOMAIN"] = old_domain


async def _seed_user_with_session(app: Starlette) -> int:
    password_service = await resolve_dependency(app, PasswordService)
    session_store = await resolve_dependency(app, SessionStore)

    password_hash = await password_service.hash(_TEST_PASSWORD_MD5)
    user = await seed_user(
        app,
        User(
            id=0,
            username=_TEST_USERNAME,
            safe_username=User.normalize_username(_TEST_USERNAME),
            email="player@example.com",
            password_hash=password_hash,
            country="JP",
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    await session_store.create(
        user.id,
        token="test-session-token",
        data=SessionData(
            user_id=user.id,
            username=user.username,
            privileges=0,
            country="JP",
            osu_version="b20231130",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
        ),
    )
    return user.id


def _build_beatmap(
    *,
    beatmap_id: int,
    beatmapset_id: int,
    checksum: str,
    official_status: BeatmapRankStatus,
) -> Beatmap:
    return Beatmap(
        id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=checksum,
        mode=BeatmapMode.OSU,
        version="Insane",
        total_length=240,
        hit_length=220,
        max_combo=1234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=official_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _build_beatmapset(
    *,
    beatmapset_id: int,
    artist: str,
    title: str,
    beatmap: Beatmap,
    official_status: BeatmapRankStatus,
) -> BeatmapSet:
    return BeatmapSet(
        id=beatmapset_id,
        artist=artist,
        title=title,
        creator="Author",
        artist_unicode=None,
        title_unicode=None,
        official_status=official_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


async def _seed_known_ranked_beatmap(app: Starlette) -> None:
    beatmap = _build_beatmap(
        beatmap_id=75,
        beatmapset_id=1,
        checksum=_KNOWN_CHECKSUM,
        official_status=BeatmapRankStatus.RANKED,
    )
    beatmapset = _build_beatmapset(
        beatmapset_id=1,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        beatmap=beatmap,
        official_status=BeatmapRankStatus.RANKED,
    )
    await seed_beatmapset(app, beatmapset)


async def _seed_not_submitted_beatmap(app: Starlette) -> None:
    beatmap = _build_beatmap(
        beatmap_id=999,
        beatmapset_id=99,
        checksum=_KNOWN_CHECKSUM,
        official_status=BeatmapRankStatus.NOT_SUBMITTED,
    )
    beatmapset = _build_beatmapset(
        beatmapset_id=99,
        artist="UnknownArtist",
        title="UnknownTitle",
        beatmap=beatmap,
        official_status=BeatmapRankStatus.NOT_SUBMITTED,
    )
    await seed_beatmapset(app, beatmapset)


async def _seed_converted_mode_ranked_beatmap(app: Starlette) -> None:
    beatmap = _build_beatmap(
        beatmap_id=75,
        beatmapset_id=_FIXTURE_SET_ID,
        checksum=_FIXTURE_CHECKSUM,
        official_status=BeatmapRankStatus.RANKED,
    )
    beatmapset = _build_beatmapset(
        beatmapset_id=_FIXTURE_SET_ID,
        artist="Suzaku",
        title="Anisakis -sakuya-",
        beatmap=beatmap,
        official_status=BeatmapRankStatus.RANKED,
    )
    await seed_beatmapset(app, beatmapset)


async def _seed_update_candidate_beatmap(app: Starlette) -> None:
    """Same-set filename checksum mismatch用のbeatmapとfile attachmentを作成する。

    Args:
        app (Starlette): In-memory provider graphを持つintegration test app。

    Returns:
        None: Update candidateがquery repositoryから解決可能になったことを表す。

    Raises:
        Exception: Beatmap seedまたはfile attachment作成が失敗した場合。
    """
    beatmap = _build_beatmap(
        beatmap_id=75,
        beatmapset_id=1,
        checksum=_KNOWN_CHECKSUM,
        official_status=BeatmapRankStatus.RANKED,
    )
    beatmapset = _build_beatmapset(
        beatmapset_id=1,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        beatmap=beatmap,
        official_status=BeatmapRankStatus.RANKED,
    )
    await seed_beatmapset(app, beatmapset)
    _ = await attach_beatmap_file(
        app,
        BeatmapFileAttachment(
            beatmap_id=beatmap.id,
            blob_id=1,
            checksum_md5=_KNOWN_CHECKSUM,
            source=BeatmapFileSource.LEGACY_OFFICIAL,
            original_filename=_UPDATE_FILENAME,
            fetched_at=_NOW,
            verified_at=_NOW,
        ),
    )


def _query(
    *,
    checksum: str | None = _KNOWN_CHECKSUM,
    username: str | None = _TEST_USERNAME,
    password_md5: str | None = _TEST_PASSWORD_MD5,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    params: dict[str, str] = {}
    if checksum is not None:
        params["c"] = checksum
    if username is not None:
        params["us"] = username
    if password_md5 is not None:
        params["ha"] = password_md5
    _ = params.setdefault("s", "0")
    _ = params.setdefault("vv", "4")
    _ = params.setdefault("v", "1")
    _ = params.setdefault("m", "0")
    _ = params.setdefault("mods", "0")
    if extra is not None:
        params.update(extra)
    return params


def _assert_getscores_contract_response(
    response: httpx2.Response,
    shape_id: GetscoresWireShapeId,
) -> None:
    """Runtime responseをcanonical wire shape fixtureへ照合する。

    Args:
        response (httpx2.Response): Integration endpointから返されたresponse。
        shape_id (GetscoresWireShapeId): 期待するcanonical response shape ID。

    Returns:
        None: Status、header、body、terminal LFが全て一致したことを表す。

    Raises:
        KeyError: Known shape IDがtyped evidence bundleに存在しない場合。
        AssertionError: Client-visible response contractがfixtureと異なる場合。
    """
    fixture = _GETSCORES_SHAPES[shape_id]
    expected_headers = dict(fixture.required_headers)
    observed_headers = {
        header: response.headers.get(header) for header in fixture.required_headers
    }
    expected_body = read_getscores_expected_body(_GETSCORES_EVIDENCE, shape_id)
    terminal_lf_count = len(response.content) - len(response.content.rstrip(b"\n"))

    assert response.status_code == fixture.http_status
    assert observed_headers == expected_headers
    assert all(header not in response.headers for header in fixture.absent_headers)
    assert response.content == expected_body
    assert terminal_lf_count == fixture.terminal_lf_count


async def _override_mirror_resolve(
    app: Starlette,
    *,
    metadata_status: BeatmapFetchState,
) -> None:
    """Seed the new query-side fetch-state seam for an unknown checksum."""
    target = BeatmapFetchTarget.metadata_by_checksum(_UNKNOWN_CHECKSUM)
    await seed_beatmap_fetch_state(app, target, metadata_status, _NOW)


# ---------------------------------------------------------------------------
# Unavailable wire-format coverage (Req 5.2, 5.3, 5.5, 5.6, 5.7, 5.8, 7.1-7.4)
# ---------------------------------------------------------------------------


class TestUnavailableShortBodies:
    """Every UNAVAILABLE outcome path returns the ``-1|false`` short body."""

    def test_not_submitted_status_returns_short_body(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _seed_not_submitted_beatmap(app)

                asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(),
                )
                _assert_getscores_contract_response(
                    response,
                    GetscoresWireShapeId.UNAVAILABLE,
                )

    @pytest.mark.parametrize(
        "case_id",
        [
            "missing-beatmap-identity",
            "invalid-checksum",
            "unavailable-beatmap",
        ],
    )
    def test_symbolic_unavailable_case_matches_canonical_shape(self, case_id: str) -> None:
        """Symbolic unavailable caseをexact response fixtureへ照合する。

        Args:
            case_id (str): Canonical branch catalogのunavailable case ID。

        Returns:
            None: Status、header、body、terminal LFが一致したことを表す。

        Raises:
            KeyError: Canonical branch caseがtyped evidence bundleに存在しない場合。
            AssertionError: Runtime responseがunavailable fixtureと異なる場合。
        """
        case = _GETSCORES_CASES[case_id]
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                _ = asyncio.run(_seed_user_with_session(app))
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=build_getscores_contract_query(case, _query()),
                )
                _assert_getscores_contract_response(response, case.expected_shape_id)

    def test_pending_after_wait_returns_short_body(self) -> None:
        """Mirror returns PENDING_FETCH -> resolver UNAVAILABLE(pending_fetch)."""
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _override_mirror_resolve(
                        app, metadata_status=BeatmapFetchState.PENDING_FETCH
                    )

                asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(checksum=_UNKNOWN_CHECKSUM),
                )
                _assert_getscores_contract_response(
                    response,
                    GetscoresWireShapeId.UNAVAILABLE,
                )

    def test_failed_metadata_returns_short_body(self) -> None:
        """Mirror returns FAILED -> resolver UNAVAILABLE(failed_metadata)."""
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _override_mirror_resolve(app, metadata_status=BeatmapFetchState.FAILED)

                asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(checksum=_UNKNOWN_CHECKSUM),
                )
                _assert_getscores_contract_response(
                    response,
                    GetscoresWireShapeId.UNAVAILABLE,
                )


# ---------------------------------------------------------------------------
# UpdateAvailable end-to-end body (Req 6.1, 6.2)
# ---------------------------------------------------------------------------


class TestUpdateAvailableBody:
    """Checksum miss with same set+filename and different stored checksum -> ``1|false``."""

    def test_update_available_returns_short_body(self) -> None:
        case = _GETSCORES_CASES["update-candidate"]
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _seed_update_candidate_beatmap(app)

                asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=build_getscores_contract_query(
                        case,
                        _query(
                            extra={
                                "f": _UPDATE_FILENAME,
                                "i": "1",
                            },
                        ),
                    ),
                )
                _assert_getscores_contract_response(response, case.expected_shape_id)


# ---------------------------------------------------------------------------
# Post-selection failure invariance (Requirement 1.6)
# ---------------------------------------------------------------------------


class TestShortResponseFailureInvariance:
    """Preparation/warmup例外後も選択済みshort responseを維持する。"""

    def test_metadata_preparation_exception_preserves_update_shape(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Metadata preparation例外後もcanonical update responseを返す。

        Args:
            monkeypatch (pytest.MonkeyPatch): Public resolver methodを一時置換するfixture。

        Returns:
            None: 選択済みupdate shapeが例外で置換されないことを表す。

        Raises:
            AssertionError: Runtime responseがcanonical update fixtureと異なる場合。
        """
        metadata_calls: list[BeatmapResolveOptions | None] = []

        async def _raise_metadata_preparation(
            _service: BeatmapMirrorService,
            _checksum_md5: str,
            _options: BeatmapResolveOptions | None = None,
        ) -> BeatmapResolveResult:
            metadata_calls.append(_options)
            raise RuntimeError("synthetic getscores metadata preparation failure")

        monkeypatch.setattr(
            BeatmapMirrorService,
            "resolve_by_checksum",
            _raise_metadata_preparation,
        )
        case = _GETSCORES_CASES["update-candidate"]

        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _seed_update_candidate_beatmap(app)

                asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=build_getscores_contract_query(
                        case,
                        _query(extra={"f": _UPDATE_FILENAME, "i": "1"}),
                    ),
                )

        _assert_getscores_contract_response(response, case.expected_shape_id)
        assert len(metadata_calls) == 1

    def test_warmup_exception_preserves_unavailable_shape(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Beatmap file warmup例外後もcanonical unavailable responseを返す。

        Args:
            monkeypatch (pytest.MonkeyPatch): Public warmup use-case methodを一時置換するfixture。

        Returns:
            None: 選択済みunavailable shapeが例外で置換されないことを表す。

        Raises:
            AssertionError: Runtime responseがcanonical unavailable fixtureと異なる場合。
        """
        warmup_requests: list[BeatmapFileWarmupRequest] = []

        async def _raise_warmup(
            _use_case: RequestBeatmapFileWarmupUseCase,
            request: BeatmapFileWarmupRequest,
        ) -> BeatmapFileWarmupResult:
            warmup_requests.append(request)
            raise RuntimeError("synthetic getscores beatmap file warmup failure")

        monkeypatch.setattr(
            RequestBeatmapFileWarmupUseCase,
            "execute",
            _raise_warmup,
        )
        case = _GETSCORES_CASES["unavailable-beatmap"]

        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                _ = asyncio.run(_seed_user_with_session(app))
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=build_getscores_contract_query(case, _query()),
                )

        _assert_getscores_contract_response(response, case.expected_shape_id)
        assert len(warmup_requests) == 1


# ---------------------------------------------------------------------------
# Auth disclosure prevention (Req 2.2, 2.3, 2.4)
# ---------------------------------------------------------------------------


class TestAuthDisclosureRegression:
    """Auth failures must return 401 with no body — even when beatmap is seeded."""

    def test_invalid_credentials_returns_empty_401(self) -> None:
        case = _GETSCORES_CASES["auth-invalid"]
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _seed_known_ranked_beatmap(app)

                asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=build_getscores_contract_query(case, _query()),
                )
                _assert_getscores_contract_response(response, case.expected_shape_id)

    def test_no_session_returns_empty_401(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _seed_user_and_map_no_session() -> None:
                    password_service = await resolve_dependency(app, PasswordService)
                    password_hash = await password_service.hash(_TEST_PASSWORD_MD5)
                    _ = await seed_user(
                        app,
                        User(
                            id=0,
                            username=_TEST_USERNAME,
                            safe_username=User.normalize_username(_TEST_USERNAME),
                            email="player@example.com",
                            password_hash=password_hash,
                            country="JP",
                            created_at=_NOW,
                            updated_at=_NOW,
                        ),
                    )
                    await _seed_known_ranked_beatmap(app)

                asyncio.run(_seed_user_and_map_no_session())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(),
                )
                _assert_getscores_contract_response(
                    response,
                    GetscoresWireShapeId.AUTH_FAILURE,
                )


# ---------------------------------------------------------------------------
# Parse-only control invariance (Req 10.4, 10.5, 10.6, 3.8, 3.9)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ParseOnlyCase:
    name: str
    overrides: dict[str, str]


_PARSE_ONLY_CASES = (
    _ParseOnlyCase(name="baseline", overrides={}),
    _ParseOnlyCase(name="m_taiko", overrides={"m": "1"}),
    _ParseOnlyCase(name="m_ctb", overrides={"m": "2"}),
    _ParseOnlyCase(name="m_mania", overrides={"m": "3"}),
    _ParseOnlyCase(name="mods_dthr", overrides={"mods": "72"}),
    _ParseOnlyCase(name="s_song_select", overrides={"s": "1"}),
    _ParseOnlyCase(name="v_friends", overrides={"v": "3"}),
    _ParseOnlyCase(name="vv_5", overrides={"vv": "5"}),
)
_PARSE_ONLY_IDS = tuple(c.name for c in _PARSE_ONLY_CASES)


class TestParseOnlyInvariance:
    """``m``, ``mods``, ``s``, ``v``, ``vv`` do not vary MVP header output."""

    def _exercise(self, overrides: dict[str, str]) -> bytes:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _seed_known_ranked_beatmap(app)

                asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra=overrides),
                )
                assert response.status_code == HTTPStatus.OK
                return response.content

    @pytest.mark.parametrize("case", _PARSE_ONLY_CASES, ids=_PARSE_ONLY_IDS)
    def test_parse_only_field_does_not_vary_header(self, case: _ParseOnlyCase) -> None:
        baseline = self._exercise({})
        observed = self._exercise(case.overrides)
        assert observed == baseline, (
            f"Parse-only override {case.overrides!r} altered MVP header output"
        )


# ---------------------------------------------------------------------------
# Converted-mode fixture iteration (Req 13.1, 13.2, 10.4)
# ---------------------------------------------------------------------------


def _load_converted_mode_fixture() -> tuple[dict[str, object], ...]:
    with _CONVERTED_FIXTURE_PATH.open(encoding="utf-8") as handle:
        data: object = json.load(handle)  # pyright: ignore[reportAny]
    assert isinstance(data, list)
    entries: list[dict[str, object]] = []
    for raw in data:  # pyright: ignore[reportUnknownVariableType]
        assert isinstance(raw, dict)
        entry: dict[str, object] = {}
        for key, value in raw.items():  # pyright: ignore[reportUnknownVariableType]
            assert isinstance(key, str)
            entry[key] = value
        entries.append(entry)
    return tuple(entries)


_CONVERTED_FIXTURE_ENTRIES = _load_converted_mode_fixture()
_CONVERTED_FIXTURE_IDS = tuple(
    str(entry.get("description", f"entry-{idx}"))
    for idx, entry in enumerate(_CONVERTED_FIXTURE_ENTRIES)
)


class TestConvertedModeFixture:
    """Each converted-mode fixture request produces the same wire status."""

    @pytest.mark.parametrize(
        "entry",
        _CONVERTED_FIXTURE_ENTRIES,
        ids=_CONVERTED_FIXTURE_IDS,
    )
    def test_converted_mode_request_yields_expected_status(self, entry: dict[str, object]) -> None:
        raw_query = entry["query"]
        expected_status = entry["expected_status"]
        assert isinstance(raw_query, dict)
        assert isinstance(expected_status, int)

        query: dict[str, str] = {}
        for key, value in raw_query.items():  # pyright: ignore[reportUnknownVariableType]
            assert isinstance(key, str)
            assert isinstance(value, str)
            query[key] = value

        # Override auth credentials so the fixture is exercised against the
        # seeded test user/session without leaking fixture credentials.
        query["us"] = _TEST_USERNAME
        query["ha"] = _TEST_PASSWORD_MD5

        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _seed_converted_mode_ranked_beatmap(app)

                asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=query,
                )
                assert response.status_code == HTTPStatus.OK
                first_line = response.content.split(b"\n")[0]
                parts = first_line.split(b"|")
                assert int(parts[0]) == expected_status
                assert parts[1] == b"false"
                assert int(parts[2]) == 75
                assert int(parts[3]) == _FIXTURE_SET_ID
