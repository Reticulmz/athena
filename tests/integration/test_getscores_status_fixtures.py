"""End-to-end status-fixture validation for the legacy getscores endpoint.

Drives the endpoint through ``osu.$DOMAIN`` with seeded users, sessions, and
beatmaps for each submitted ``BeatmapRankStatus`` (Ranked, Loved, Qualified,
Pending, WIP, Graveyard) and asserts the wire response satisfies:

- status wire value mapping (Ranked=2, Loved=5, Qualified=4,
  Pending/WIP/Graveyard=0)
- ``beatmap_id`` and ``beatmapset_id`` are surfaced verbatim
- ``score_count`` is ``0`` and ``failed`` flag is ``false``
- display title formatted as ``[bold:0,size:20]<artist>|<title>``
- rating line is ``0`` (no rating in MVP)
- no score rows or personal-best rows
- official behavior precedence: Pending / WIP / Graveyard return header bodies
  (not short ``<status>|false`` bodies as bancho.py does)
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
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
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.queries.identity.password_service import PasswordService
from tests.support.app import create_in_memory_app as create_app
from tests.support.app import resolve_dependency
from tests.support.persistence import seed_beatmapset, seed_user

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette


_TEST_USERNAME = "StableUser"
_TEST_PASSWORD_PLAIN = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD_PLAIN.encode()).hexdigest()
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


@dataclass(frozen=True)
class _StatusFixture:
    """Per-status seed data and expected wire output."""

    name: str
    rank_status: BeatmapRankStatus
    expected_wire_status: int
    beatmap_id: int
    beatmapset_id: int
    checksum: str
    artist: str
    title: str


_FIXTURES = (
    _StatusFixture(
        name="ranked",
        rank_status=BeatmapRankStatus.RANKED,
        expected_wire_status=2,
        beatmap_id=75,
        beatmapset_id=1,
        checksum="0123456789abcdef0123456789abcdef",
        artist="Suzaku",
        title="Anisakis -sakuya-",
    ),
    _StatusFixture(
        name="loved",
        rank_status=BeatmapRankStatus.LOVED,
        expected_wire_status=5,
        beatmap_id=500,
        beatmapset_id=50,
        checksum="11111111111111111111111111111111",
        artist="Hatsune Miku",
        title="World is Mine -Full ver.-",
    ),
    _StatusFixture(
        name="qualified",
        rank_status=BeatmapRankStatus.QUALIFIED,
        expected_wire_status=4,
        beatmap_id=1200,
        beatmapset_id=100,
        checksum="22222222222222222222222222222222",
        artist="DECO*27",
        title="Ghost Rule",
    ),
    _StatusFixture(
        name="pending",
        rank_status=BeatmapRankStatus.PENDING,
        expected_wire_status=0,
        beatmap_id=2500,
        beatmapset_id=200,
        checksum="33333333333333333333333333333333",
        artist="t+pazolite",
        title="Oshama Scramble!",
    ),
    _StatusFixture(
        name="wip",
        rank_status=BeatmapRankStatus.WIP,
        expected_wire_status=0,
        beatmap_id=3000,
        beatmapset_id=250,
        checksum="44444444444444444444444444444444",
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
    ),
    _StatusFixture(
        name="graveyard",
        rank_status=BeatmapRankStatus.GRAVEYARD,
        expected_wire_status=0,
        beatmap_id=4500,
        beatmapset_id=400,
        checksum="55555555555555555555555555555555",
        artist="xi",
        title="Freedom Dive",
    ),
)
_FIXTURE_IDS = tuple(f.name for f in _FIXTURES)
_BELOW_RANKED_FIXTURES = tuple(f for f in _FIXTURES if f.expected_wire_status == 0)
_BELOW_RANKED_IDS = tuple(f.name for f in _BELOW_RANKED_FIXTURES)


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


async def _seed_beatmap_for_fixture(app: Starlette, fixture: _StatusFixture) -> None:
    beatmap = Beatmap(
        id=fixture.beatmap_id,
        beatmapset_id=fixture.beatmapset_id,
        checksum_md5=fixture.checksum,
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
        official_status=fixture.rank_status,
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
        id=fixture.beatmapset_id,
        artist=fixture.artist,
        title=fixture.title,
        creator="Author",
        artist_unicode=None,
        title_unicode=None,
        official_status=fixture.rank_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )
    await seed_beatmapset(app, beatmapset)


def _query_for_fixture(fixture: _StatusFixture) -> dict[str, str]:
    return {
        "c": fixture.checksum,
        "us": _TEST_USERNAME,
        "ha": _TEST_PASSWORD_MD5,
        "s": "0",
        "vv": "4",
        "v": "1",
        "m": "0",
        "mods": "0",
    }


def _exercise_endpoint(fixture: _StatusFixture) -> bytes:
    """Boot the app, seed dependencies for a fixture, and return the body."""
    with _test_env():
        app = create_app()
        with TestClient(
            app,
            base_url="http://osu.athena.localhost",
            raise_server_exceptions=False,
        ) as client:

            async def _setup() -> None:
                _ = await _seed_user_with_session(app)
                await _seed_beatmap_for_fixture(app, fixture)

            asyncio.run(_setup())
            response = client.get(
                "/web/osu-osz2-getscores.php",
                params=_query_for_fixture(fixture),
            )
            assert response.status_code == HTTPStatus.OK
            assert response.headers["content-type"].startswith("text/plain")
            return response.content


# ---------------------------------------------------------------------------
# Per-fixture wire-format checks
# ---------------------------------------------------------------------------


class TestSubmittedStatusFixtures:
    """Each submitted status produces a header response with the expected fields."""

    @pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
    def test_status_line_fields(self, fixture: _StatusFixture) -> None:
        body = _exercise_endpoint(fixture)
        first_line = body.split(b"\n")[0]
        parts = first_line.split(b"|")
        # Format: <status>|false|<beatmap_id>|<beatmapset_id>|0||
        assert int(parts[0]) == fixture.expected_wire_status
        assert parts[1] == b"false"
        assert int(parts[2]) == fixture.beatmap_id
        assert int(parts[3]) == fixture.beatmapset_id
        assert parts[4] == b"0", "score_count must be 0"
        # Trailing || produces two empty tail entries
        assert parts[-2] == b""
        assert parts[-1] == b""

    @pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
    def test_offset_line_is_zero(self, fixture: _StatusFixture) -> None:
        body = _exercise_endpoint(fixture)
        lines = body.split(b"\n")
        assert lines[1] == b"0", "Beatmap offset line must be '0' in MVP"

    @pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
    def test_display_title_line_format(self, fixture: _StatusFixture) -> None:
        body = _exercise_endpoint(fixture)
        lines = body.split(b"\n")
        display = lines[2]
        expected = f"[bold:0,size:20]{fixture.artist}|{fixture.title}".encode()
        assert display == expected

    @pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
    def test_rating_line_is_zero(self, fixture: _StatusFixture) -> None:
        body = _exercise_endpoint(fixture)
        lines = body.split(b"\n")
        assert lines[3] == b"0", "Rating line must be '0' in MVP"

    @pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
    def test_no_score_rows_or_personal_best(self, fixture: _StatusFixture) -> None:
        body = _exercise_endpoint(fixture)
        lines = body.split(b"\n")
        # Header body shape: 4 data lines + 2 blank trailing lines (placeholder
        # for personal-best and score-rows sections), terminated by final LF.
        # split('\n') therefore produces: 4 data + 2 empty + 1 trailing empty = 7.
        non_empty = [line for line in lines if line]
        assert len(non_empty) == 4, (
            f"Expected exactly 4 data lines (status, offset, display, rating); got {non_empty!r}"
        )
        # Confirm trailing placeholder lines exist (two blank sections).
        assert lines[-3:] == [b"", b"", b""], (
            f"Expected two trailing blank section placeholders, got tail {lines[-3:]!r}"
        )


# ---------------------------------------------------------------------------
# Official-precedence assertions: Pending / WIP / Graveyard return headers
# ---------------------------------------------------------------------------


class TestOfficialPrecedenceOverBanchopy:
    """Pending/WIP/Graveyard return full header bodies, never short bodies."""

    @pytest.mark.parametrize(
        "fixture",
        _BELOW_RANKED_FIXTURES,
        ids=_BELOW_RANKED_IDS,
    )
    def test_below_ranked_returns_header_body_not_short(self, fixture: _StatusFixture) -> None:
        body = _exercise_endpoint(fixture)
        # Short bodies are exactly b"-1|false" or b"1|false"; header bodies
        # are multi-line and contain the display title with the bbcode prefix.
        assert body != b"-1|false"
        assert body != b"1|false"
        assert b"[bold:0,size:20]" in body, (
            f"{fixture.name} must return a header body (bancho.py would short-respond)"
        )


# ---------------------------------------------------------------------------
# Provenance must never leak into stable response body
# ---------------------------------------------------------------------------


class TestStableResponsePurity:
    """Header bodies must not include any internal provenance fields."""

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

    @pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
    def test_no_provenance_tokens_in_body(self, fixture: _StatusFixture) -> None:
        body = _exercise_endpoint(fixture)
        for token in self._BANNED_TOKENS:
            assert token not in body, (
                f"{fixture.name} body contains internal provenance token {token!r}"
            )
