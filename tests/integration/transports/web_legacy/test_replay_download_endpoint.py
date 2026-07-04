"""Replay download legacy endpoint integration smoke tests."""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from starlette.testclient import TestClient
from tests.support.app import create_in_memory_app as create_app
from tests.support.app import resolve_dependency
from tests.support.credentials import FIXED_TEST_PASSWORD_MD5
from tests.support.persistence import seed_role, seed_user

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.domain.scores.mods import ModCombination
from osu_server.domain.scores.replay import Replay
from osu_server.domain.scores.score import Grade, Playstyle, Ruleset, Score
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.storage.blob_storage import BlobStorageService
from osu_server.services.queries.identity.password_service import PasswordService

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from starlette.applications import Starlette

_NOW = datetime(2026, 7, 5, tzinfo=UTC)
_TEST_USERNAME = "ReplayUser"
_VISIBLE_ROLE = Role(
    id=401,
    name="Replay Visible",
    permissions=Privileges.NORMAL | Privileges.UNRESTRICTED,
    position=0,
)


@contextmanager
def _test_env() -> Generator[None]:
    old_environment = os.environ.get("ENVIRONMENT")
    old_domain = os.environ.get("DOMAIN")
    os.environ["ENVIRONMENT"] = "test"
    os.environ["DOMAIN"] = "athena.localhost"
    _ = os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/athena")
    _ = os.environ.setdefault("VALKEY_URL", "redis://localhost:6379")
    try:
        yield
    finally:
        if old_environment is None:
            _ = os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = old_environment
        if old_domain is None:
            _ = os.environ.pop("DOMAIN", None)
        else:
            os.environ["DOMAIN"] = old_domain


def test_replay_download_route_returns_empty_401_for_auth_failure(tmp_path: Path) -> None:
    with _test_env():
        app = create_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("http://osu.athena.localhost/web/osu-getreplay.php")

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.content == b""


def test_replay_download_route_returns_empty_404_for_missing_replay(tmp_path: Path) -> None:
    with _test_env():
        app = create_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            score_id = asyncio.run(_seed_authenticated_visible_score(app))

            response = client.get(
                "http://osu.athena.localhost/web/osu-getreplay.php",
                params=_query(score_id),
            )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.content == b""


def test_replay_download_route_keeps_available_replay_blocked(tmp_path: Path) -> None:
    with _test_env():
        app = create_app(blob_root=tmp_path / "blobs")
        with TestClient(app, raise_server_exceptions=False) as client:
            score_id = asyncio.run(_seed_authenticated_visible_score(app))
            asyncio.run(_attach_available_replay(app, score_id=score_id))

            response = client.get(
                "http://osu.athena.localhost/web/osu-getreplay.php",
                params=_query(score_id),
            )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.content == b""


async def _seed_authenticated_visible_score(app: Starlette) -> int:
    user_id = await _seed_authenticated_user(app)
    return await _seed_visible_score(app, user_id=user_id)


async def _seed_authenticated_user(app: Starlette) -> int:
    password_service = await resolve_dependency(app, PasswordService)
    session_store = await resolve_dependency(app, SessionStore)
    password_hash = await password_service.hash(FIXED_TEST_PASSWORD_MD5)
    user = await seed_user(
        app,
        User(
            id=0,
            username=_TEST_USERNAME,
            safe_username=User.normalize_username(_TEST_USERNAME),
            email="replay-user@example.com",
            password_hash=password_hash,
            country="JP",
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    await _assign_visible_role(app, user.id)
    await session_store.create(
        user.id,
        "replay-download-session",
        data=SessionData(
            user_id=user.id,
            username=user.username,
            privileges=int(Privileges.NORMAL | Privileges.UNRESTRICTED),
            country="JP",
            osu_version="b20260705",
            utc_offset=9,
            display_city=False,
            client_hashes="",
            pm_private=False,
            role_ids=(_VISIBLE_ROLE.id,),
        ),
    )
    return user.id


async def _assign_visible_role(app: Starlette, user_id: int) -> None:
    await seed_role(app, _VISIBLE_ROLE)
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        await uow.roles.assign_role(user_id, _VISIBLE_ROLE.id)
        await uow.commit()


async def _seed_visible_score(app: Starlette, *, user_id: int) -> int:
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        score = await uow.scores.create(
            Score(
                id=None,
                user_id=user_id,
                beatmap_id=75,
                beatmap_checksum="replay-download-checksum",
                online_checksum="replay-download-online-checksum",
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
                client_version="b20260705",
                submitted_at=_NOW,
                beatmap_status_at_submission="ranked",
                leaderboard_eligible_at_submission=True,
            )
        )
        await uow.commit()
    assert score.id is not None
    return score.id


async def _attach_available_replay(app: Starlette, *, score_id: int) -> None:
    blob_storage = await resolve_dependency(app, BlobStorageService)
    stored = await blob_storage.put_bytes(
        b"synthetic-replay-download-body",
        content_type="application/octet-stream",
    )
    blob = stored.blob
    uow_factory = await resolve_dependency(app, UnitOfWorkFactory)
    async with uow_factory() as uow:
        _ = await uow.replays.create(
            Replay(
                id=None,
                score_id=score_id,
                blob_id=blob.id,
                checksum_sha256=blob.sha256,
                byte_size=blob.byte_size,
            )
        )
        await uow.commit()


def _query(score_id: int) -> dict[str, str]:
    return {
        "c": str(score_id),
        "h": FIXED_TEST_PASSWORD_MD5,
        "m": str(Ruleset.OSU.value),
        "u": _TEST_USERNAME,
    }
