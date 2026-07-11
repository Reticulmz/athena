"""Integration tests for leaderboard reconciliation public correctness."""

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
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.domain.scores.leaderboards import ScoreRankKey
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardUserBestScope,
    UpsertBeatmapLeaderboardUserBest,
)
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.scores.leaderboards import (
    RebuildBeatmapLeaderboardsForBeatmapsetCommand,
    RebuildBeatmapLeaderboardsForBeatmapsetUseCase,
    RebuildBeatmapLeaderboardsForUserCommand,
    RebuildBeatmapLeaderboardsForUserUseCase,
)
from osu_server.services.queries.identity.password_service import PasswordService
from tests.support.app import create_in_memory_app as create_app
from tests.support.app import resolve_dependency
from tests.support.persistence import seed_beatmapset, seed_role, seed_user

if TYPE_CHECKING:
    from collections.abc import Generator

    from starlette.applications import Starlette


_TEST_USERNAME = "StableUser"
_TEST_PASSWORD_PLAIN = "ExamplePass1234"  # gitleaks:allow
_TEST_PASSWORD_MD5 = hashlib.md5(_TEST_PASSWORD_PLAIN.encode()).hexdigest()
_KNOWN_CHECKSUM = "0123456789abcdef0123456789abcdef"
_REPLACEMENT_CHECKSUM = "fedcba9876543210fedcba9876543210"
_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_LEADERBOARD_VISIBLE_ROLE = Role(
    id=100,
    name="Leaderboard Visible",
    permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
    position=0,
)


@dataclass(frozen=True, slots=True)
class _StableScoreRow:
    score_id: int
    username: str
    score: int
    user_id: int
    rank: int


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


async def _seed_user_with_session(app: Starlette, *, country: str = "JP") -> int:
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
        "test-session-token",
        SessionData(
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


async def _remove_leaderboard_visible_roles(app: Starlette, user_id: int) -> None:
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        await uow.roles.set_roles_for_user(user_id, ())
        await uow.commit()


async def _seed_known_beatmap(
    app: Starlette,
    *,
    checksum: str = _KNOWN_CHECKSUM,
    status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
) -> None:
    beatmap = Beatmap(
        id=75,
        beatmapset_id=1,
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
        official_status=status,
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
        official_status=status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )
    await seed_beatmapset(app, beatmapset)


async def _seed_score_with_projection(
    app: Starlette,
    *,
    user_id: int,
    checksum: str = _KNOWN_CHECKSUM,
) -> int:
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        score = await uow.scores.create(
            Score(
                id=None,
                user_id=user_id,
                beatmap_id=75,
                beatmap_checksum=checksum,
                online_checksum="reconciliation-visible-score",
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
                mods=ModCombination.none(),
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
                beatmap_status_at_submission=BeatmapRankStatus.RANKED,
                leaderboard_eligible_at_submission=True,
            )
        )
        assert score.id is not None
        _ = await uow.beatmap_leaderboards.upsert_if_better(
            UpsertBeatmapLeaderboardUserBest(
                scope=BeatmapLeaderboardUserBestScope(
                    beatmap_id=75,
                    beatmap_checksum=checksum,
                    ruleset=Ruleset.OSU,
                    playstyle=Playstyle.VANILLA,
                    user_id=user_id,
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


async def _run_user_rebuild_twice(app: Starlette, *, user_id: int) -> None:
    use_case = await resolve_dependency(app, RebuildBeatmapLeaderboardsForUserUseCase)
    for index in range(2):
        result = await use_case.execute(
            RebuildBeatmapLeaderboardsForUserCommand(
                user_id=user_id,
                reason=f"integration-user-rebuild-{index}",
            )
        )
        assert result.target_found


async def _run_beatmapset_rebuild_twice(app: Starlette) -> None:
    use_case = await resolve_dependency(app, RebuildBeatmapLeaderboardsForBeatmapsetUseCase)
    for index in range(2):
        result = await use_case.execute(
            RebuildBeatmapLeaderboardsForBeatmapsetCommand(
                beatmapset_id=1,
                reason=f"integration-beatmapset-rebuild-{index}",
            )
        )
        assert result.target_found


def _query(
    *,
    checksum: str = _KNOWN_CHECKSUM,
) -> dict[str, str]:
    return {
        "c": checksum,
        "us": _TEST_USERNAME,
        "ha": _TEST_PASSWORD_MD5,
        "s": "0",
        "vv": "4",
        "v": "1",
        "m": "0",
        "mods": "0",
    }


def _get_header(client: TestClient, *, checksum: str = _KNOWN_CHECKSUM) -> GetscoresHeader:
    response = client.get(
        "/web/osu-osz2-getscores.php",
        params=_query(checksum=checksum),
    )
    assert response.status_code == HTTPStatus.OK
    parsed = parse_getscores_response(response.content)
    assert parsed.error is None
    assert parsed.response is not None
    assert parsed.response.kind is GetscoresResponseKind.HEADER
    assert parsed.response.header is not None
    return parsed.response.header


def _assert_not_submitted_response(
    client: TestClient,
    *,
    checksum: str = _KNOWN_CHECKSUM,
) -> None:
    response = client.get(
        "/web/osu-osz2-getscores.php",
        params=_query(checksum=checksum),
    )
    assert response.status_code == HTTPStatus.OK
    assert response.content == b"-1|false"
    parsed = parse_getscores_response(response.content)
    assert parsed.error is None
    assert parsed.response is not None
    assert parsed.response.kind is GetscoresResponseKind.NOT_SUBMITTED
    assert parsed.response.header is None


def _score_rows(header: GetscoresHeader) -> tuple[_StableScoreRow, ...]:
    return tuple(_parse_score_row(row) for row in header.score_rows)


def _personal_best_row(header: GetscoresHeader) -> _StableScoreRow | None:
    if header.personal_best_row is None:
        return None
    return _parse_score_row(header.personal_best_row)


def _parse_score_row(row: str) -> _StableScoreRow:
    fields = row.split("|")
    assert len(fields) == 16
    return _StableScoreRow(
        score_id=int(fields[0]),
        username=fields[1],
        score=int(fields[2]),
        user_id=int(fields[12]),
        rank=int(fields[13]),
    )


def test_pending_rebuild_public_output_uses_current_filters_and_rebuild_converges() -> None:
    with _test_env():
        app = create_app()
        with TestClient(
            app,
            base_url="http://osu.athena.localhost",
            raise_server_exceptions=False,
        ) as client:

            async def _setup() -> tuple[int, int]:
                viewer_id = await _seed_user_with_session(app)
                await _seed_known_beatmap(app)
                score_id = await _seed_score_with_projection(app, user_id=viewer_id)
                return viewer_id, score_id

            viewer_id, score_id = asyncio.run(_setup())

            initial_header = _get_header(client)
            initial_rows = _score_rows(initial_header)
            initial_pb = _personal_best_row(initial_header)
            assert initial_header.score_count == 1
            assert [row.score_id for row in initial_rows] == [score_id]
            assert initial_pb is not None
            assert initial_pb.score_id == score_id

            asyncio.run(_remove_leaderboard_visible_roles(app, viewer_id))
            hidden_user_header = _get_header(client)
            assert hidden_user_header.score_count == 0
            assert hidden_user_header.personal_best_row is None
            assert hidden_user_header.score_rows == ()

            asyncio.run(_assign_leaderboard_visible_role(app, viewer_id))
            visible_again_header = _get_header(client)
            assert [row.score_id for row in _score_rows(visible_again_header)] == [score_id]
            asyncio.run(_run_user_rebuild_twice(app, user_id=viewer_id))
            visible_after_rebuild_header = _get_header(client)
            assert _score_rows(visible_after_rebuild_header) == _score_rows(visible_again_header)
            assert _personal_best_row(visible_after_rebuild_header) == _personal_best_row(
                visible_again_header
            )

            asyncio.run(_seed_known_beatmap(app, status=BeatmapRankStatus.NOT_SUBMITTED))
            _assert_not_submitted_response(client)
            asyncio.run(_run_beatmapset_rebuild_twice(app))
            _assert_not_submitted_response(client)

            asyncio.run(
                _seed_known_beatmap(
                    app,
                    checksum=_REPLACEMENT_CHECKSUM,
                    status=BeatmapRankStatus.RANKED,
                )
            )
            checksum_changed_header = _get_header(client, checksum=_REPLACEMENT_CHECKSUM)
            assert checksum_changed_header.score_count == 0
            assert checksum_changed_header.personal_best_row is None
            assert checksum_changed_header.score_rows == ()
            asyncio.run(_run_beatmapset_rebuild_twice(app))
            checksum_after_rebuild_header = _get_header(client, checksum=_REPLACEMENT_CHECKSUM)
            assert checksum_after_rebuild_header.score_count == 0
            assert checksum_after_rebuild_header.personal_best_row is None
            assert checksum_after_rebuild_header.score_rows == ()
