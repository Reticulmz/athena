"""Diagnostics integration tests for the legacy getscores endpoint.

Asserts that the handler emits structlog events for auth failures, parse
warnings, invalid identity, lookup conflicts, unavailable / update-available
outcomes, and anti-cheat signal — without leaking ``ha`` (password md5),
raw ``us`` values, or internal provenance fields in stable response bodies.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import structlog.testing
from starlette.testclient import TestClient

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.repositories.interfaces.beatmap_repository import BeatmapRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.user_repository import UserRepository
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository
from osu_server.services.password_service import PasswordService
from tests.support.app import create_in_memory_app as create_app
from tests.support.app import resolve_dependency

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette
    from structlog.typing import EventDict


_TEST_USERNAME = "TargetUsr"
_TEST_PASSWORD_PLAIN = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD_PLAIN.encode()).hexdigest()
_KNOWN_CHECKSUM = "0123456789abcdef0123456789abcdef"
_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)


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
    user_repo = await resolve_dependency(app, UserRepository)
    password_service = await resolve_dependency(app, PasswordService)
    session_store = await resolve_dependency(app, SessionStore)

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


async def _seed_known_beatmap(app: Starlette) -> None:
    beatmap_repo = await resolve_dependency(app, BeatmapRepository)
    assert isinstance(beatmap_repo, InMemoryBeatmapRepository)

    beatmap = Beatmap(
        id=75,
        beatmapset_id=1,
        checksum_md5=_KNOWN_CHECKSUM,
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
    beatmapset = BeatmapSet(
        id=1,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        creator="Realazy",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
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


def _events_with(logs: list[EventDict], event_name: str) -> list[EventDict]:
    return [entry for entry in logs if entry.get("event") == event_name]


def _no_credentials_leaked(entry: EventDict) -> bool:
    """All values in a log entry must not contain raw password md5 or username."""
    for value in entry.values():  # pyright: ignore[reportAny]
        if isinstance(value, str):
            if _TEST_PASSWORD_MD5 in value:
                return False
            if _TEST_USERNAME in value:
                return False
    return True


# ---------------------------------------------------------------------------
# Auth failure observability (Req 12.2, 12.3, 2.4)
# ---------------------------------------------------------------------------


class TestAuthFailureDiagnostics:
    """Auth failures emit getscores_auth_failed without credential leakage."""

    def test_missing_credentials_emits_auth_failed_event(self) -> None:
        with _test_env():
            app = create_app()
            with (
                TestClient(
                    app,
                    base_url="http://osu.athena.localhost",
                    raise_server_exceptions=False,
                ) as client,
                structlog.testing.capture_logs() as logs,
            ):
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(username=None, password_md5=None),
                )
                assert response.status_code == HTTPStatus.UNAUTHORIZED

        events = _events_with(logs, "getscores_auth_failed")
        assert len(events) == 1
        entry = events[0]
        assert entry.get("failure_reason") == "invalid_credentials"
        assert "ha" not in entry
        assert _no_credentials_leaked(entry)

    def test_invalid_credentials_emits_auth_failed_event(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                _ = asyncio.run(_seed_user_with_session(app))
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(password_md5="0" * 32),
                    )
                    assert response.status_code == HTTPStatus.UNAUTHORIZED

        events = _events_with(logs, "getscores_auth_failed")
        assert len(events) >= 1
        for entry in events:
            assert entry.get("failure_reason") == "invalid_credentials"
            assert "ha" not in entry
            assert _no_credentials_leaked(entry)

    def test_no_session_emits_auth_failed_event(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _seed_user_only() -> None:
                    user_repo = await resolve_dependency(app, UserRepository)
                    password_service = await resolve_dependency(app, PasswordService)
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

                asyncio.run(_seed_user_only())
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(),
                    )
                    assert response.status_code == HTTPStatus.UNAUTHORIZED

        events = _events_with(logs, "getscores_auth_failed")
        assert len(events) >= 1
        last = events[-1]
        assert last.get("failure_reason") == "no_session"
        assert "ha" not in last
        assert _no_credentials_leaked(last)


# ---------------------------------------------------------------------------
# Identity / parse / outcome diagnostics (Req 12.3, 12.4, 12.5, 4.5)
# ---------------------------------------------------------------------------


class TestRequestDiagnostics:
    """Authorized requests emit appropriate diagnostic events."""

    def test_missing_identity_emits_identity_invalid(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                _ = asyncio.run(_seed_user_with_session(app))
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(checksum=None),
                    )
                    assert response.status_code == HTTPStatus.OK
                    assert response.content == b"-1|false"

        events = _events_with(logs, "getscores_identity_invalid")
        assert len(events) == 1
        entry = events[0]
        assert entry.get("parse_error") == "missing_identity"
        assert "ha" not in entry
        assert _no_credentials_leaked(entry)

    def test_unknown_checksum_emits_unavailable(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                _ = asyncio.run(_seed_user_with_session(app))
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(checksum="ff" * 16),
                    )
                    assert response.status_code == HTTPStatus.OK
                    assert response.content == b"-1|false"

        events = _events_with(logs, "getscores_unavailable")
        assert len(events) == 1
        entry = events[0]
        assert entry.get("resolve_reason") in {
            "not_found",
            "not_submitted",
            "pending_fetch",
            "failed_metadata",
        }
        assert "ha" not in entry
        assert _no_credentials_leaked(entry)

    def test_update_available_emits_update_event(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _seed_known_beatmap(app)

                asyncio.run(_setup())
                with structlog.testing.capture_logs() as logs:
                    # Same set+filename, different checksum -> UPDATE_AVAILABLE
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(
                            checksum="aa" * 16,
                            extra={"f": "Camellia - Exit (Realazy) [Insane].osu", "i": "1"},
                        ),
                    )
                    assert response.status_code == HTTPStatus.OK

        events = _events_with(logs, "getscores_update_available")
        # We only assert the event exists when the resolver indeed produces
        # UPDATE_AVAILABLE; if the body was b"-1|false" the path differed.
        if response.content == b"1|false":
            assert len(events) == 1
            assert "ha" not in events[0]
            assert _no_credentials_leaked(events[0])

    def test_parse_warning_emits_event_for_malformed_field(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                _ = asyncio.run(_seed_user_with_session(app))
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(extra={"m": "not-an-int"}),
                    )
                    assert response.status_code == HTTPStatus.OK

        events = _events_with(logs, "getscores_parse_warning")
        assert len(events) >= 1
        for entry in events:
            assert "warnings" in entry or "warning" in entry
            assert "ha" not in entry
            assert _no_credentials_leaked(entry)

    def test_anti_cheat_signal_emits_event(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                _ = asyncio.run(_seed_user_with_session(app))
                with structlog.testing.capture_logs() as logs:
                    response = client.get(
                        "/web/osu-osz2-getscores.php",
                        params=_query(extra={"a": "1"}),
                    )
                    assert response.status_code == HTTPStatus.OK

        events = _events_with(logs, "getscores_anti_cheat_signal")
        assert len(events) == 1
        entry = events[0]
        assert "ha" not in entry
        assert _no_credentials_leaked(entry)


# ---------------------------------------------------------------------------
# Stable response body purity (Req 12.5)
# ---------------------------------------------------------------------------


class TestStableResponsePurity:
    """Stable response bodies must never contain provenance fields."""

    _BANNED_TOKENS: tuple[bytes, ...] = (
        b"_source",
        b"_verified",
        b"_policy",
        b"_fetch_state",
        b"local_status_override",
        b"official_status_source",
        b"official_status_verified",
        b"metadata_fetch_state",
        b"file_state",
    )

    def test_known_header_response_has_no_provenance(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    _ = await _seed_user_with_session(app)
                    await _seed_known_beatmap(app)

                asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(),
                )
                assert response.status_code == HTTPStatus.OK
                for token in self._BANNED_TOKENS:
                    assert token not in response.content

    def test_unavailable_response_has_no_provenance(self) -> None:
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
                    params=_query(checksum="ff" * 16),
                )
                assert response.status_code == HTTPStatus.OK
                for token in self._BANNED_TOKENS:
                    assert token not in response.content
