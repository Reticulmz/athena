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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

from starlette.testclient import TestClient

from athena_cli.stable_verification.parsers import (
    GetscoresHeader,
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
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.domain.scores.leaderboards import ScoreRankKey, projection_keys_for_score
from osu_server.domain.scores.mods import Mod, ModCombination
from osu_server.domain.scores.personal_best import LeaderboardCategory, PersonalBestScope
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBestScope,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.interfaces.commands.personal_bests import UpsertPersonalBest
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.queries.identity.password_service import PasswordService
from tests.support.app import create_in_memory_app as create_app
from tests.support.app import resolve_dependency
from tests.support.persistence import seed_beatmapset, seed_role, seed_user

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette


_TEST_USERNAME = "TargetUsr"
_TEST_PASSWORD_PLAIN = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD_PLAIN.encode()).hexdigest()
_KNOWN_CHECKSUM = "0123456789abcdef0123456789abcdef"
_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_LEADERBOARD_VISIBLE_ROLE = Role(
    id=100,
    name="Leaderboard Visible",
    permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
    position=0,
)


@dataclass(frozen=True, slots=True)
class _SeededLeaderboardScore:
    score_id: int
    user_id: int
    score: int
    mods: int


@dataclass(frozen=True, slots=True)
class _StableScoreRow:
    score_id: int
    username: str
    score: int
    mods: int
    user_id: int
    rank: int


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


async def _seed_user_with_session(app: Starlette, *, country: str = "JP") -> int:
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
            country=country,
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
            country=country,
            osu_version="b20231130",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
        ),
    )
    await _assign_leaderboard_visible_role(app, user.id)
    return user.id


async def _assign_leaderboard_visible_role(app: Starlette, user_id: int) -> None:
    await seed_role(app, _LEADERBOARD_VISIBLE_ROLE)
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        await uow.roles.assign_role(user_id, _LEADERBOARD_VISIBLE_ROLE.id)
        await uow.commit()


async def _seed_visible_user(
    app: Starlette,
    *,
    username: str,
    country: str = "JP",
) -> int:
    user = await seed_user(
        app,
        User(
            id=0,
            username=username,
            safe_username=User.normalize_username(username),
            email=f"{User.normalize_username(username)}@example.com",
            password_hash="!test-password-hash",
            country=country,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    await _assign_leaderboard_visible_role(app, user.id)
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


async def _seed_leaderboard_best(app: Starlette, *, user_id: int) -> int:
    """Seed a score and current beatmap leaderboard projection for getscores."""
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
                leaderboard_eligible_at_submission=True,
            )
        )
        assert score.id is not None
        _ = await uow.beatmap_leaderboards.upsert_if_better(
            UpsertBeatmapLeaderboardUserBest(
                scope=BeatmapLeaderboardUserBestScope(
                    beatmap_id=75,
                    ruleset=Ruleset.OSU,
                    playstyle=Playstyle.VANILLA,
                    user_id=user_id,
                    mod_filter_key=None,
                ),
                score_id=score.id,
                rank_key=ScoreRankKey(
                    score=score.score,
                    submitted_at=score.submitted_at,
                    score_id=score.id,
                ),
            )
        )
        await uow.commit()
        return score.id


async def _seed_leaderboard_score(
    app: Starlette,
    *,
    user_id: int,
    score_value: int,
    mods: ModCombination | None = None,
    submitted_offset_seconds: int = 0,
) -> _SeededLeaderboardScore:
    """Seed a score and every matching leaderboard projection key."""
    score_mods = mods if mods is not None else ModCombination.none()
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        score = await uow.scores.create(
            Score(
                id=None,
                user_id=user_id,
                beatmap_id=75,
                beatmap_checksum=_KNOWN_CHECKSUM,
                online_checksum=(
                    f"getscores-score-{user_id}-{score_value}-"
                    f"{score_mods.to_persistence_bitmask()}"
                ),
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                mods=score_mods,
                n300=300,
                n100=2,
                n50=1,
                geki=5,
                katu=4,
                miss=3,
                score=score_value,
                max_combo=1_234,
                accuracy=98.76,
                grade=Grade.S,
                passed=True,
                perfect=True,
                client_version="b20260617",
                submitted_at=_NOW + timedelta(seconds=submitted_offset_seconds),
                beatmap_status_at_submission="ranked",
                leaderboard_eligible_at_submission=True,
            )
        )
        assert score.id is not None
        for mod_filter_key in projection_keys_for_score(score.mods):
            _ = await uow.beatmap_leaderboards.upsert_if_better(
                UpsertBeatmapLeaderboardUserBest(
                    scope=BeatmapLeaderboardUserBestScope(
                        beatmap_id=75,
                        ruleset=Ruleset.OSU,
                        playstyle=Playstyle.VANILLA,
                        user_id=user_id,
                        mod_filter_key=mod_filter_key,
                    ),
                    score_id=score.id,
                    rank_key=ScoreRankKey(
                        score=score.score,
                        submitted_at=score.submitted_at,
                        score_id=score.id,
                    ),
                )
            )
        await uow.commit()
        return _SeededLeaderboardScore(
            score_id=score.id,
            user_id=user_id,
            score=score.score,
            mods=score.mods.to_persistence_bitmask(),
        )


async def _add_friend_relationships(
    app: Starlette,
    relationships: tuple[tuple[int, int], ...],
) -> None:
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        for owner_user_id, target_user_id in relationships:
            _ = await uow.friends.add_relationship(owner_user_id, target_user_id)
        await uow.commit()


async def _seed_selected_mod_scenario(app: Starlette) -> None:
    viewer_id = await _seed_user_with_session(app)
    await _seed_known_beatmap(app)
    sd_user_id = await _seed_visible_user(app, username="SuddenDeath")
    pf_user_id = await _seed_visible_user(app, username="Perfect")
    mirror_user_id = await _seed_visible_user(app, username="Mirror")
    nc_user_id = await _seed_visible_user(app, username="Nightcore")
    dt_user_id = await _seed_visible_user(app, username="DoubleTime")
    _ = await _seed_leaderboard_score(
        app,
        user_id=viewer_id,
        score_value=1_000_000,
    )
    _ = await _seed_leaderboard_score(
        app,
        user_id=sd_user_id,
        score_value=1_100_000,
        mods=ModCombination(Mod.SUDDEN_DEATH),
    )
    _ = await _seed_leaderboard_score(
        app,
        user_id=pf_user_id,
        score_value=900_000,
        mods=ModCombination(Mod.PERFECT),
    )
    _ = await _seed_leaderboard_score(
        app,
        user_id=mirror_user_id,
        score_value=800_000,
        mods=ModCombination(Mod.MIRROR),
    )
    _ = await _seed_leaderboard_score(
        app,
        user_id=nc_user_id,
        score_value=1_200_000,
        mods=ModCombination(Mod.NIGHTCORE),
    )
    _ = await _seed_leaderboard_score(
        app,
        user_id=dt_user_id,
        score_value=1_150_000,
        mods=ModCombination(Mod.DOUBLE_TIME),
    )


async def _seed_legacy_personal_best(app: Starlette, *, user_id: int) -> int:
    """Seed only the retired personal best projection for fallback regression checks."""
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        score = await uow.scores.create(
            Score(
                id=None,
                user_id=user_id,
                beatmap_id=75,
                beatmap_checksum=_KNOWN_CHECKSUM,
                online_checksum="getscores-legacy-pb-online-checksum",
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
                leaderboard_eligible_at_submission=True,
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


def _parse_header(body: bytes) -> GetscoresHeader:
    parsed = parse_getscores_response(body)
    assert parsed.error is None
    assert parsed.response is not None
    assert parsed.response.kind is GetscoresResponseKind.HEADER
    assert parsed.response.header is not None
    return parsed.response.header


def _parse_personal_best_row(header: GetscoresHeader) -> _StableScoreRow | None:
    if header.personal_best_row is None:
        return None
    return _parse_score_row(header.personal_best_row)


def _parse_score_rows(header: GetscoresHeader) -> tuple[_StableScoreRow, ...]:
    return tuple(_parse_score_row(row) for row in header.score_rows)


def _parse_score_row(row: str) -> _StableScoreRow:
    fields = row.split("|")
    assert len(fields) == 16
    return _StableScoreRow(
        score_id=int(fields[0]),
        username=fields[1],
        score=int(fields[2]),
        mods=int(fields[11]),
        user_id=int(fields[12]),
        rank=int(fields[13]),
    )


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

    def test_known_checksum_returns_personal_best_and_top_rows_separately(self) -> None:
        """Authorized request returns PB separately from leaderboard rows."""
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
                    score_id = await _seed_leaderboard_best(app, user_id=user_id)
                    return score_id, user_id

                score_id, user_id = asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(),
                )

                assert response.status_code == HTTPStatus.OK
                lines = response.content.split(b"\n")
                assert lines[0] == b"2|false|75|1|1||"
                expected_row = (
                    f"{score_id}|{_TEST_USERNAME}|987654|1234|1|2|300|3|4|5|1|24|"
                    f"{user_id}|1|{int(_NOW.timestamp())}|0"
                ).encode()
                assert lines[4] == expected_row
                assert lines[5] == expected_row
                parsed = parse_getscores_response(response.content)
                assert parsed.error is None
                assert parsed.response is not None
                assert parsed.response.header is not None
                assert parsed.response.header.personal_best_row == lines[4].decode()
                assert parsed.response.header.score_rows == (lines[5].decode(),)
                assert not parsed.response.header.empty_leaderboard

    def test_legacy_personal_best_projection_is_not_used_as_score_row(self) -> None:
        """Old PB projection does not create fallback leaderboard rows."""
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    user_id = await _seed_user_with_session(app)
                    await _seed_known_beatmap(app)
                    _ = await _seed_legacy_personal_best(app, user_id=user_id)

                _ = asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(),
                )

                assert response.status_code == HTTPStatus.OK
                lines = response.content.split(b"\n")
                assert lines[0] == b"2|false|75|1|0||"
                parsed = parse_getscores_response(response.content)
                assert parsed.error is None
                assert parsed.response is not None
                assert parsed.response.header is not None
                assert parsed.response.header.personal_best_row is None
                assert parsed.response.header.score_rows == ()

    def test_global_local_and_country_categories_return_expected_scope_rows(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    viewer_id = await _seed_user_with_session(app)
                    await _seed_known_beatmap(app)
                    japan_rival_id = await _seed_visible_user(
                        app,
                        username="JapanRival",
                        country="JP",
                    )
                    us_rival_id = await _seed_visible_user(
                        app,
                        username="UnitedStatesRival",
                        country="US",
                    )
                    _ = await _seed_leaderboard_score(
                        app,
                        user_id=viewer_id,
                        score_value=900_000,
                        submitted_offset_seconds=3,
                    )
                    _ = await _seed_leaderboard_score(
                        app,
                        user_id=japan_rival_id,
                        score_value=1_100_000,
                        submitted_offset_seconds=2,
                    )
                    _ = await _seed_leaderboard_score(
                        app,
                        user_id=us_rival_id,
                        score_value=1_200_000,
                        submitted_offset_seconds=1,
                    )

                asyncio.run(_setup())

                local_response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra={"v": "1"}),
                )
                assert local_response.status_code == HTTPStatus.OK
                local_header = _parse_header(local_response.content)
                local_rows = _parse_score_rows(local_header)
                local_pb = _parse_personal_best_row(local_header)

                assert local_header.score_count == 3
                assert [row.username for row in local_rows] == [
                    "UnitedStatesRival",
                    "JapanRival",
                    _TEST_USERNAME,
                ]
                assert [row.rank for row in local_rows] == [1, 2, 3]
                assert local_pb is not None
                assert local_pb.username == _TEST_USERNAME
                assert local_pb.rank == 3

                country_response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra={"v": "4"}),
                )
                assert country_response.status_code == HTTPStatus.OK
                country_header = _parse_header(country_response.content)
                country_rows = _parse_score_rows(country_header)
                country_pb = _parse_personal_best_row(country_header)

                assert country_header.score_count == 2
                assert [row.username for row in country_rows] == [
                    "JapanRival",
                    _TEST_USERNAME,
                ]
                assert [row.rank for row in country_rows] == [1, 2]
                assert country_pb is not None
                assert country_pb.username == _TEST_USERNAME
                assert country_pb.rank == 2

    def test_friends_category_includes_self_and_excludes_reverse_only(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    viewer_id = await _seed_user_with_session(app)
                    await _seed_known_beatmap(app)
                    friend_id = await _seed_visible_user(app, username="FriendTarget")
                    reverse_only_id = await _seed_visible_user(
                        app,
                        username="ReverseOnly",
                    )
                    unrelated_id = await _seed_visible_user(app, username="Unrelated")
                    await _add_friend_relationships(
                        app,
                        (
                            (viewer_id, friend_id),
                            (reverse_only_id, viewer_id),
                        ),
                    )
                    _ = await _seed_leaderboard_score(
                        app,
                        user_id=viewer_id,
                        score_value=1_100_000,
                    )
                    _ = await _seed_leaderboard_score(
                        app,
                        user_id=friend_id,
                        score_value=1_200_000,
                    )
                    _ = await _seed_leaderboard_score(
                        app,
                        user_id=reverse_only_id,
                        score_value=1_300_000,
                    )
                    _ = await _seed_leaderboard_score(
                        app,
                        user_id=unrelated_id,
                        score_value=1_400_000,
                    )

                asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra={"v": "3"}),
                )

                assert response.status_code == HTTPStatus.OK
                header = _parse_header(response.content)
                rows = _parse_score_rows(header)
                personal_best = _parse_personal_best_row(header)

                assert header.score_count == 2
                assert [row.username for row in rows] == ["FriendTarget", _TEST_USERNAME]
                assert [row.rank for row in rows] == [1, 2]
                assert "ReverseOnly" not in {row.username for row in rows}
                assert personal_best is not None
                assert personal_best.username == _TEST_USERNAME
                assert personal_best.rank == 2

    def test_selected_mods_no_mod_and_mirror_behavior(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                asyncio.run(_seed_selected_mod_scenario(app))

                no_mod_response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra={"v": "2", "mods": "0"}),
                )
                assert no_mod_response.status_code == HTTPStatus.OK
                no_mod_header = _parse_header(no_mod_response.content)
                no_mod_rows = _parse_score_rows(no_mod_header)
                no_mod_pb = _parse_personal_best_row(no_mod_header)

                assert no_mod_header.score_count == 4
                assert [row.mods for row in no_mod_rows] == [
                    int(Mod.SUDDEN_DEATH),
                    int(Mod.NONE),
                    int(Mod.PERFECT),
                    int(Mod.MIRROR),
                ]
                assert int(Mod.NIGHTCORE) not in {row.mods for row in no_mod_rows}
                assert no_mod_pb is not None
                assert no_mod_pb.username == _TEST_USERNAME
                assert no_mod_pb.rank == 2

                mirror_response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra={"v": "2", "mods": str(int(Mod.MIRROR))}),
                )
                assert mirror_response.status_code == HTTPStatus.OK
                mirror_header = _parse_header(mirror_response.content)
                assert mirror_header.score_count == 0
                assert mirror_header.personal_best_row is None
                assert mirror_header.score_rows == ()

    def test_selected_mods_nc_dt_and_pf_sd_behavior(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:
                asyncio.run(_seed_selected_mod_scenario(app))

                dt_response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra={"v": "2", "mods": str(int(Mod.DOUBLE_TIME))}),
                )
                assert dt_response.status_code == HTTPStatus.OK
                dt_header = _parse_header(dt_response.content)
                assert dt_header.score_count == 2
                assert [row.mods for row in _parse_score_rows(dt_header)] == [
                    int(Mod.NIGHTCORE),
                    int(Mod.DOUBLE_TIME),
                ]
                assert dt_header.personal_best_row is None

                nc_response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra={"v": "2", "mods": str(int(Mod.NIGHTCORE))}),
                )
                assert nc_response.status_code == HTTPStatus.OK
                nc_header = _parse_header(nc_response.content)
                assert nc_header.score_count == 2
                assert [row.mods for row in _parse_score_rows(nc_header)] == [
                    int(Mod.NIGHTCORE),
                    int(Mod.DOUBLE_TIME),
                ]

                sd_response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra={"v": "2", "mods": str(int(Mod.SUDDEN_DEATH))}),
                )
                assert sd_response.status_code == HTTPStatus.OK
                sd_header = _parse_header(sd_response.content)
                assert sd_header.score_count == 2
                assert [row.mods for row in _parse_score_rows(sd_header)] == [
                    int(Mod.SUDDEN_DEATH),
                    int(Mod.PERFECT),
                ]

                pf_response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra={"v": "2", "mods": str(int(Mod.PERFECT))}),
                )
                assert pf_response.status_code == HTTPStatus.OK
                pf_header = _parse_header(pf_response.content)
                assert pf_header.score_count == 2
                assert [row.mods for row in _parse_score_rows(pf_header)] == [
                    int(Mod.SUDDEN_DEATH),
                    int(Mod.PERFECT),
                ]

    def test_global_top_50_limit_keeps_personal_best_with_actual_rank(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> _SeededLeaderboardScore:
                    viewer_id = await _seed_user_with_session(app)
                    await _seed_known_beatmap(app)
                    for index in range(50):
                        rival_id = await _seed_visible_user(
                            app,
                            username=f"TopFiftyRival{index}",
                        )
                        _ = await _seed_leaderboard_score(
                            app,
                            user_id=rival_id,
                            score_value=2_000_000 - index,
                            submitted_offset_seconds=index,
                        )
                    return await _seed_leaderboard_score(
                        app,
                        user_id=viewer_id,
                        score_value=1_000_000,
                        submitted_offset_seconds=100,
                    )

                viewer_score = asyncio.run(_setup())
                response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra={"v": "1"}),
                )

                assert response.status_code == HTTPStatus.OK
                header = _parse_header(response.content)
                rows = _parse_score_rows(header)
                personal_best = _parse_personal_best_row(header)

                assert header.score_count == 50
                assert len(rows) == 50
                assert [row.rank for row in rows] == list(range(1, 51))
                assert viewer_score.score_id not in {row.score_id for row in rows}
                assert personal_best is not None
                assert personal_best.score_id == viewer_score.score_id
                assert personal_best.rank == 51

    def test_category_specific_empty_results_keep_header_without_rows_or_pb(self) -> None:
        with _test_env():
            app = create_app()
            with TestClient(
                app,
                base_url="http://osu.athena.localhost",
                raise_server_exceptions=False,
            ) as client:

                async def _setup() -> None:
                    viewer_id = await _seed_user_with_session(app, country="XX")
                    await _seed_known_beatmap(app)
                    rival_id = await _seed_visible_user(
                        app,
                        username="CountryRival",
                        country="JP",
                    )
                    _ = await _seed_leaderboard_score(
                        app,
                        user_id=viewer_id,
                        score_value=1_000_000,
                    )
                    _ = await _seed_leaderboard_score(
                        app,
                        user_id=rival_id,
                        score_value=1_100_000,
                    )

                asyncio.run(_setup())

                country_response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra={"v": "4"}),
                )
                assert country_response.status_code == HTTPStatus.OK
                country_header = _parse_header(country_response.content)
                assert country_header.score_count == 0
                assert country_header.personal_best_row is None
                assert country_header.score_rows == ()

                unsupported_response = client.get(
                    "/web/osu-osz2-getscores.php",
                    params=_query(extra={"v": "99"}),
                )
                assert unsupported_response.status_code == HTTPStatus.OK
                unsupported_header = _parse_header(unsupported_response.content)
                assert unsupported_header.score_count == 0
                assert unsupported_header.personal_best_row is None
                assert unsupported_header.score_rows == ()

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
