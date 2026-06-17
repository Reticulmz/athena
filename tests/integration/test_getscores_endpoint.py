"""E2E integration tests for the legacy getscores endpoint.

Validates routing on osu.$DOMAIN, auth gating (401 with no beatmap data
disclosure), and stable text/plain response bodies for unavailable,
update-available, and header outcomes.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

from starlette.testclient import TestClient

from athena_cli.stable_verification.parsers import (
    GetscoresResponseKind,
    parse_getscores_response,
)
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
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.personal_best import LeaderboardCategory, PersonalBestScope
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.personal_bests import UpsertPersonalBest
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.queries.identity.password_service import PasswordService
from tests.support.app import create_in_memory_app as create_app
from tests.support.app import resolve_dependency
from tests.support.persistence import seed_beatmapset, seed_user

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette


_TEST_USERNAME = "TargetUsr"
_TEST_PASSWORD_PLAIN = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD_PLAIN.encode()).hexdigest()
_KNOWN_CHECKSUM = "0123456789abcdef0123456789abcdef"
_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)


@contextmanager
def _test_env() -> Generator[None]:
    """Temporarily set ENVIRONMENT=test for the duration of the block."""
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
    """Seed an active user + session, returning the user id."""
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


async def _seed_known_beatmap(app: Starlette) -> None:
    """Seed a known submitted beatmap into command-side persistence."""
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
    await seed_beatmapset(app, beatmapset)


async def _seed_personal_best(app: Starlette, *, user_id: int) -> int:
    """Seed a score and current personal best projection for getscores."""
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        score = await uow.scores.create(
            Score(
                id=None,
                user_id=user_id,
                beatmap_id=75,
                beatmap_checksum=_KNOWN_CHECKSUM,
                online_checksum="getscores-pb-online-checksum",
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                mods=ModCombination.from_bitmask(24),
                n300=300,
                n100=2,
                n50=1,
                geki=5,
                katu=4,
                miss=3,
                score=987_654,
                max_combo=1_234,
                accuracy=98.76,
                grade=Grade.S,
                passed=True,
                perfect=True,
                client_version="b20260617",
                submitted_at=_NOW,
                beatmap_status_at_submission="ranked",
            )
        )
        assert score.id is not None
        _ = await uow.personal_bests.upsert_if_better(
            UpsertPersonalBest(
                scope=PersonalBestScope(
                    user_id=user_id,
                    beatmap_id=75,
                    ruleset=Ruleset.OSU,
                    playstyle=Playstyle.VANILLA,
                    category=LeaderboardCategory.GLOBAL,
                ),
                score_id=score.id,
                ranking_value=score.score,
            )
        )
        await uow.commit()
        return score.id


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
    # Stable client typically also sends these; include parse-only controls
    _ = params.setdefault("s", "0")
    _ = params.setdefault("vv", "4")
    _ = params.setdefault("v", "1")
    _ = params.setdefault("m", "0")
    _ = params.setdefault("mods", "0")
    if extra is not None:
        params.update(extra)
    return params


# ---------------------------------------------------------------------------
# Routing (requirements 1.1, 1.2)
# ---------------------------------------------------------------------------


class TestRouting:
    """`/web/osu-osz2-getscores.php` is reachable on osu.$DOMAIN only."""

    def test_route_is_reachable_on_osu_host(self) -> None:
        """Routed via Host(osu.$DOMAIN); request reaches handler (200)."""
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                # Without auth → 401 confirms route reached the handler.
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(username=None, password_md5=None),
                )
                assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_route_is_not_reachable_via_path_fallback(self) -> None:
        """No path-based fallback on the default (non-osu) host."""
        with _test_env():
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(),
                )
                assert response.status_code == HTTPStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# Auth (requirements 2.1, 2.2, 2.3, 2.4)
# ---------------------------------------------------------------------------


class TestAuthorization:
    """Auth failures return 401 without beatmap data disclosure."""

    def test_missing_credentials_returns_401_empty(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(username=None, password_md5=None),
                )
                assert response.status_code == HTTPStatus.UNAUTHORIZED
                assert response.content == b""

    def test_invalid_credentials_returns_401_empty(self) -> None:
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
                    params=_query(password_md5="0" * 32),
                )
                assert response.status_code == HTTPStatus.UNAUTHORIZED
                assert response.content == b""

    def test_no_session_returns_401_empty(self) -> None:
        """Valid credentials but no active session → 401."""
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                # Seed the user without creating a session
                async def _seed_user_only() -> None:
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

                asyncio.run(_seed_user_only())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(),
                )
                assert response.status_code == HTTPStatus.UNAUTHORIZED
                assert response.content == b""


# ---------------------------------------------------------------------------
# Stable response bodies (requirements 7.1, 7.5, 11.1, 11.6)
# ---------------------------------------------------------------------------


class TestStableResponse:
    """Authorized requests receive 200 text/plain stable bodies."""

    def test_known_checksum_returns_header_body(self) -> None:
        """Authorized request with known checksum returns header body."""
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
                assert response.headers["content-type"].startswith("text/plain")
                assert "charset=utf-8" in response.headers["content-type"].lower()
                first_line = response.content.split(b"\n")[0]
                # Ranked status = 2; beatmap_id=75; beatmapset_id=1
                assert first_line == b"2|false|75|1|0||"
                parsed = parse_getscores_response(response.content)
                assert parsed.error is None
                assert parsed.response is not None
                assert parsed.response.kind is GetscoresResponseKind.HEADER
                assert parsed.response.header is not None
                assert parsed.response.header.empty_leaderboard

    def test_known_checksum_returns_personal_best_row_when_projection_exists(self) -> None:
        """Authorized request returns the current user's PB row when available."""
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> tuple[int, int]:
                    user_id = await _seed_user_with_session(app)
                    await _seed_known_beatmap(app)
                    score_id = await _seed_personal_best(app, user_id=user_id)
                    return score_id, user_id

                score_id, user_id = asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(),
                )

                assert response.status_code == HTTPStatus.OK
                lines = response.content.split(b"\n")
                assert lines[0] == b"2|false|75|1|1||"
                assert (
                    lines[4]
                    == (
                        f"{score_id}|{_TEST_USERNAME}|987654|1234|1|2|300|3|4|5|1|24|"
                        f"{user_id}|1|{int(_NOW.timestamp())}|0"
                    ).encode()
                )
                assert lines[5] == lines[4]
                parsed = parse_getscores_response(response.content)
                assert parsed.error is None
                assert parsed.response is not None
                assert parsed.response.header is not None
                assert parsed.response.header.personal_best_row == lines[4].decode()
                assert parsed.response.header.score_rows == (lines[5].decode(),)
                assert not parsed.response.header.empty_leaderboard

    def test_unknown_checksum_returns_unavailable_short_body(self) -> None:
        """Unknown checksum returns 200 -1|false."""
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
                assert response.headers["content-type"].startswith("text/plain")
                assert response.content == b"-1|false"
                parsed = parse_getscores_response(response.content)
                assert parsed.error is None
                assert parsed.response is not None
                assert parsed.response.kind is GetscoresResponseKind.NOT_SUBMITTED

    def test_missing_identity_returns_unavailable_short_body(self) -> None:
        """Missing identity (no c, no f+i) returns 200 -1|false."""
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
                parsed = parse_getscores_response(response.content)
                assert parsed.error is None
                assert parsed.response is not None
                assert parsed.response.kind is GetscoresResponseKind.NOT_SUBMITTED
