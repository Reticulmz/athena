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

from osu_server.app import create_app
from osu_server.domain.beatmap import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileAttachment,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapResolveResult,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.repositories.interfaces.beatmap_repository import BeatmapRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.user_repository import UserRepository
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository
from osu_server.services.legacy_getscores_service import GetscoresResolver
from osu_server.services.password_service import PasswordService

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette

    from osu_server.infrastructure.di.container import Container


_TEST_USERNAME = "TargetUsr"
_TEST_PASSWORD_PLAIN = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD_PLAIN.encode()).hexdigest()
_KNOWN_CHECKSUM = "0123456789abcdef0123456789abcdef"
_UPDATE_OLD_CHECKSUM = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_UNKNOWN_CHECKSUM = "f" * 32
_FIXTURE_CHECKSUM = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
_FIXTURE_SET_ID = 1
_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)

_CONVERTED_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "web_legacy"
    / "getscores"
    / "converted_mode_requests.json"
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


def _container(app: Starlette) -> Container:
    return app.state.container  # pyright: ignore[reportAny]


async def _seed_user_with_session(app: Starlette) -> int:
    container = _container(app)
    user_repo = await container.resolve(UserRepository)
    password_service = await container.resolve(PasswordService)
    session_store = await container.resolve(SessionStore)

    password_hash = await password_service.hash(_TEST_PASSWORD_MD5)
    user = await user_repo.create(
        User(
            id=0,
            username=_TEST_USERNAME,
            safe_username=User.normalize_username(_TEST_USERNAME),
            email="player@example.com",
            password_hash=password_hash,
            country="JP",
            created_at=_NOW,
            updated_at=_NOW,
        )
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
        mode="osu",
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
    container = _container(app)
    beatmap_repo = await container.resolve(BeatmapRepository)
    assert isinstance(beatmap_repo, InMemoryBeatmapRepository)
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
    await beatmap_repo.save_beatmapset_snapshot(beatmapset)


async def _seed_not_submitted_beatmap(app: Starlette) -> None:
    container = _container(app)
    beatmap_repo = await container.resolve(BeatmapRepository)
    assert isinstance(beatmap_repo, InMemoryBeatmapRepository)
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
    await beatmap_repo.save_beatmapset_snapshot(beatmapset)


async def _seed_converted_mode_ranked_beatmap(app: Starlette) -> None:
    container = _container(app)
    beatmap_repo = await container.resolve(BeatmapRepository)
    assert isinstance(beatmap_repo, InMemoryBeatmapRepository)
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
    await beatmap_repo.save_beatmapset_snapshot(beatmapset)


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


async def _override_mirror_resolve(
    app: Starlette,
    *,
    metadata_status: BeatmapFetchState,
) -> None:
    """Inject a stub mirror callable that returns the requested metadata state."""
    container = _container(app)
    resolver = await container.resolve(GetscoresResolver)

    async def _stub(
        _checksum: str,
        _options: object,
    ) -> BeatmapResolveResult:
        del _checksum, _options
        return BeatmapResolveResult(
            beatmap=None,
            beatmapset=None,
            eligibility=None,
            metadata_status=metadata_status,
            file_status=BeatmapFileState.MISSING,
            source=None,
            verified=False,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=None,
        )

    resolver._mirror_resolve = _stub  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


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
                assert response.status_code == HTTPStatus.OK
                assert response.headers["content-type"].startswith("text/plain")
                assert response.content == b"-1|false"

    def test_unknown_checksum_returns_short_body(self) -> None:
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
                    params=_query(checksum=_UNKNOWN_CHECKSUM),
                )
                assert response.status_code == HTTPStatus.OK
                assert response.content == b"-1|false"

    def test_missing_identity_returns_short_body(self) -> None:
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
                    params=_query(checksum=None),
                )
                assert response.status_code == HTTPStatus.OK
                assert response.content == b"-1|false"

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
                assert response.status_code == HTTPStatus.OK
                assert response.content == b"-1|false"

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
                assert response.status_code == HTTPStatus.OK
                assert response.content == b"-1|false"


# ---------------------------------------------------------------------------
# UpdateAvailable end-to-end body (Req 6.1, 6.2)
# ---------------------------------------------------------------------------


class TestUpdateAvailableBody:
    """Checksum miss with same set+filename and different stored checksum -> ``1|false``."""

    def test_update_available_returns_short_body(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    container = _container(app)
                    beatmap_repo = await container.resolve(BeatmapRepository)
                    assert isinstance(beatmap_repo, InMemoryBeatmapRepository)

                    filename = "Camellia - Exit (Realazy) [Insane].osu"
                    attachment_checksum = _KNOWN_CHECKSUM
                    beatmap = Beatmap(
                        id=75,
                        beatmapset_id=1,
                        checksum_md5=attachment_checksum,
                        mode="osu",
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
                    beatmapset = _build_beatmapset(
                        beatmapset_id=1,
                        artist="Camellia",
                        title="Exit This Earth's Atomosphere",
                        beatmap=beatmap,
                        official_status=BeatmapRankStatus.RANKED,
                    )
                    await beatmap_repo.save_beatmapset_snapshot(beatmapset)

                    # Attach the .osu with the filename so the filename-in-set
                    # lookup succeeds independently of mirror availability.
                    _ = await beatmap_repo.attach_osu_file(
                        BeatmapFileAttachment(
                            beatmap_id=75,
                            blob_id=1,
                            checksum_md5=attachment_checksum,
                            source="legacy_official",
                            original_filename=filename,
                            fetched_at=_NOW,
                            verified_at=_NOW,
                        )
                    )

                asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(
                        checksum=_UPDATE_OLD_CHECKSUM,
                        extra={
                            "f": "Camellia - Exit (Realazy) [Insane].osu",
                            "i": "1",
                        },
                    ),
                )
                assert response.status_code == HTTPStatus.OK
                assert response.headers["content-type"].startswith("text/plain")
                assert response.content == b"1|false"


# ---------------------------------------------------------------------------
# Auth disclosure prevention (Req 2.2, 2.3, 2.4)
# ---------------------------------------------------------------------------


class TestAuthDisclosureRegression:
    """Auth failures must return 401 with no body — even when beatmap is seeded."""

    def test_invalid_credentials_returns_empty_401(self) -> None:
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
                    params=_query(password_md5="0" * 32),
                )
                assert response.status_code == HTTPStatus.UNAUTHORIZED
                assert response.content == b""

    def test_no_session_returns_empty_401(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _seed_user_and_map_no_session() -> None:
                    container = _container(app)
                    user_repo = await container.resolve(UserRepository)
                    password_service = await container.resolve(PasswordService)
                    password_hash = await password_service.hash(_TEST_PASSWORD_MD5)
                    _ = await user_repo.create(
                        User(
                            id=0,
                            username=_TEST_USERNAME,
                            safe_username=User.normalize_username(_TEST_USERNAME),
                            email="player@example.com",
                            password_hash=password_hash,
                            country="JP",
                            created_at=_NOW,
                            updated_at=_NOW,
                        )
                    )
                    await _seed_known_ranked_beatmap(app)

                asyncio.run(_seed_user_and_map_no_session())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(),
                )
                assert response.status_code == HTTPStatus.UNAUTHORIZED
                assert response.content == b""


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
